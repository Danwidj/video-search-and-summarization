# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3-E reference driver (offline; no model call). Writes packets and images for the Claude Code passes and reads
their answers back. Every step is resumable: an answered packet is never rewritten.

    uv run --frozen python scripts/v2_c3e.py visibility --out DIR [--half dev|test|all]
    uv run --frozen python scripts/v2_c3e.py boxes --out DIR --half dev --run RUN_DIR [--run RUN_DIR ...]
    uv run --frozen python scripts/v2_c3e.py status --out DIR

``DIR`` is private (under the gitignored data root). RA1's frames, frame limits and detector proposals are read
from ``--ra1`` (default ``<data-root>/v2/references/box-references-v1``) and never written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL))

from evalv2.core.hashing import canonical_json  # noqa: E402
from evalv2.core.private import ensure_private  # noqa: E402
from evalv2.datasets import generation_prompts  # noqa: E402
from evalv2.datasets.ground_truth import half, load_gt_v1, load_split_v2  # noqa: E402
from evalv2.references import boxes, c3e, c3e_review, c3e_v2  # noqa: E402
from evalv2.references.passes import FilePass, packet_sha256  # noqa: E402

GEN_MODEL = "claude-opus-5-5"


def identity(prompt: str, model: str = GEN_MODEL) -> dict:
    import hashlib

    return {"model": model, "prompt": prompt,
            "prompt_sha256": hashlib.sha256(generation_prompts.prompt_text(prompt).encode()).hexdigest()}


def clips_of(halves: str, gt: dict) -> dict[str, list[str]]:
    split = load_split_v2()
    names = ("dev", "test") if halves == "all" else (halves,)
    return {name: half(split, name, gt_split=gt["split"]) for name in names}


def frame_ends(ra1: Path) -> dict[str, float]:
    limits = json.loads((ra1 / "frame-limits-v1.json").read_text(encoding="utf-8"))
    return {clip: float(row["end_s"]) for clip, row in limits["clips"].items()}


def visibility(args: argparse.Namespace) -> dict:
    gt = load_gt_v1(data_root=args.data_root)
    ends = frame_ends(args.ra1)
    out = {"packets_written": 0, "sheets": 0, "clips": 0, "answered": 0}
    for name, clips in clips_of(args.half, gt).items():
        for packet in c3e.visibility_packets(gt, clips, ends):
            out["clips"] += 1
            c3e.assert_visibility_blind(packet["validator"], packet["generator"])
            for role, prompt in (("generator", c3e.VISIBILITY_GENERATOR_PROMPT),
                                 ("validator", c3e.VISIBILITY_VALIDATOR_PROMPT)):
                body = dict(packet[role], half=name)
                for sheet in body["sheets"]:
                    target = args.out / "images" / sheet["sheet"]
                    if not target.exists():
                        c3e.render_sheet(args.ra1 / "frames", packet["clip"], sheet["tiles"], target)
                    out["sheets"] += 1
                fp = FilePass(args.out / "visibility" / role, identity(prompt))
                if fp.answer(f"c3e-vis-{role[:3]}-{packet['clip']}", body) is None:
                    out["packets_written"] += len(fp.written)
                else:
                    out["answered"] += 1
    return out


def box_prepare(args: argparse.Namespace) -> dict:
    gt = load_gt_v1(data_root=args.data_root)
    ends = frame_ends(args.ra1)
    [(name, clips)] = clips_of(args.half, gt).items()
    evidence = [row for run in args.run for row in c3e.evidence_seconds(run)]
    planned = c3e.plan(gt, clips, ends, evidence, half=name)
    plan_dir = args.out / "boxes" / name
    ensure_private(plan_dir)
    plan_dir.mkdir(parents=True, exist_ok=True)
    sampling = {"version": planned["version"], "half": name, "seed": planned["seed"],
                "runs": [str(r) for r in args.run], "sampling": planned["sampling"]}
    body = canonical_json(sampling)
    target = plan_dir / "sampling.json"  # who chose which second: never shown to an annotator or reviewer
    if target.exists() and target.read_bytes() != body:
        raise SystemExit(f"{target} exists with another sampling; a changed sampling is a new directory")
    target.write_bytes(body)
    generator = FilePass(plan_dir / "generator", identity(boxes_prompt := "gen-box-select-v1"))
    validator = FilePass(plan_dir / "validator", {**identity("gen-box-validate-v1"),
                                                  "id": f"{GEN_MODEL}:gen-box-validate-v1"})
    counts = {"items": 0, "generator_frames": 0, "frames_with_marks": 0, "validator_written": 0,
              "pending_generator": 0, "pending_validator": 0, "done": 0, "problems": []}
    for packet in c3e.box_packets(planned, args.ra1 / "proposals", generator_prompt=boxes_prompt,
                                  validator_prompt="gen-box-validate-v1"):
        counts["items"] += 1
        gen = packet["generator"]
        for frame in gen["frames"]:
            counts["generator_frames"] += 1
            counts["frames_with_marks"] += bool(frame["marks"])
            image = plan_dir / "images" / frame["image"]
            if not image.exists():
                c3e.draw_marks(args.ra1 / "frames", packet["item"]["clip"], frame, image)
        reply = generator.answer(f"c3e-gen-{packet['key']}", gen)
        if reply is None:
            counts["pending_generator"] += 1
            continue
        try:
            boxes.assert_blind(packet["validator"], gen, reply.get("answers", reply))
        except boxes.BoxReferenceError as exc:
            counts["problems"].append({"item": packet["key"], "stage": "assert_blind", "problem": str(exc)[:160]})
            continue
        for frame in packet["validator"]["frames"]:
            image = plan_dir / "images" / frame["image"]
            if not image.exists():
                c3e.draw_marks(args.ra1 / "frames", packet["item"]["clip"], frame, image)
        if validator.answer(f"c3e-val-{packet['key']}", packet["validator"]) is None:
            counts["pending_validator"] += 1
        else:
            counts["done"] += 1
    counts["validator_written"] = len(validator.written)
    counts["sampling_sha256"] = packet_sha256(sampling)
    return counts


def _answer(root: Path, packet_id: str) -> tuple[dict, dict | None]:
    packet = json.loads((root / "packets" / f"{packet_id}.json").read_text(encoding="utf-8"))
    path = root / "answers" / f"{packet_id}.json"
    if not path.exists():
        return packet, None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("packet_sha256") != packet["packet_sha256"]:
        raise SystemExit(f"{path} answers another version of {packet_id}")
    return packet, data["answer"]


def review_build(args: argparse.Namespace) -> dict:
    """Review items for one half from the passes' answers, the reviewer configuration and the local page."""
    gt = load_gt_v1(data_root=args.data_root)
    ends = frame_ends(args.ra1)
    [(name, clips)] = clips_of(args.half, gt).items()
    sampling_path = args.out / "boxes" / name / "sampling.json"
    sampling = json.loads(sampling_path.read_text(encoding="utf-8"))["sampling"] if sampling_path.exists() else {}
    vis = args.out / "visibility"
    box_dir = args.out / "boxes" / name
    items, counts = {}, {"items": 0, "items_without_intervals": 0, "box_rows": 0, "items_waiting_for_boxes": 0}
    for clip in clips:
        gen_packet, gen_answer = _answer(vis / "generator", f"c3e-vis-gen-{clip}")
        val_packet, val_answer = _answer(vis / "validator", f"c3e-vis-val-{clip}")
        votes_g = c3e.visibility_votes(gen_packet["packet"], gen_answer) if gen_answer else {}
        votes_v = c3e.visibility_votes(val_packet["packet"], val_answer) if val_answer else {}
        category = gt["by_incident_id"][clip]["category"]
        for item in c3e.items_for(gt, [clip]):
            interval = None
            if gen_answer and val_answer:
                interval = c3e.interval_proposal(votes_g[item["item_id"]], votes_v[item["item_id"]], ends[clip])
            else:
                counts["items_without_intervals"] += 1
            entry = sampling.get(clip, {}).get(item["kind"])
            seconds = sorted(set(entry["anchors"]) | set(entry["decoys"])) if entry else []
            generated, validated = {}, {}
            if seconds:
                key = f"{clip}-{item['item_id']}"
                gp, ga = _answer(box_dir / "generator", f"c3e-gen-{key}")
                if ga is None or not (box_dir / "validator" / "answers" / f"c3e-val-{key}.json").exists():
                    counts["items_waiting_for_boxes"] += 1
                    continue
                vp, va = _answer(box_dir / "validator", f"c3e-val-{key}")
                generated = boxes.boxes_by_second(gp["packet"], ga.get("answers", ga))
                validated = boxes.boxes_by_second(vp["packet"], va.get("answers", va),
                                                  offset_s=boxes.VALIDATOR_OFFSET_S)
            row = c3e_review.proposals(item, interval, generated, validated, seconds)
            row.update({"half": name, "category": category})
            items[row["key"]] = row
            counts["items"] += 1
            counts["box_rows"] += len(row["boxes"])
    review = args.out / "review" / name
    review.mkdir(parents=True, exist_ok=True)
    config_path = review / "review-config.json"
    if config_path.exists() and not args.reassign:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if args.reviewers and config["reviewers"] != args.reviewers.split(","):
            raise SystemExit("review-config.json exists with other reviewers: pass --reassign to change it")
    else:
        if not args.reviewers:
            raise SystemExit("--reviewers ID1,ID2,... (team member ids, at least two) is needed for a new config")
        config = c3e_review.assign(list(items.values()), args.reviewers.split(","))
        config_path.write_text(json.dumps(config, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (review / "review-data.json").write_text(json.dumps({"half": name, "items": items}, sort_keys=True),
                                             encoding="utf-8")
    page = EVAL / "evalv2" / "references" / "c3e_review_page.html"
    (review / "index.html").write_bytes(page.read_bytes())
    (review / "returns").mkdir(exist_ok=True)
    frames = review / "frames"
    if not frames.exists():
        frames.symlink_to(args.ra1 / "frames")
    videos = review / "videos"
    videos.mkdir(exist_ok=True)
    manifest = json.loads((EVAL / "eval_reproducibility" / "dataset-manifest-v1.json").read_text(encoding="utf-8"))
    for clip in manifest["clips"]:
        if clip["incident_id"] in clips:
            link = videos / f"{clip['incident_id']}.mp4"
            if not link.exists():
                link.symlink_to(args.data_root / Path(clip["local_path"]).relative_to("eval_data"))
    counts["review_dir"] = str(review)
    counts["second_review_items"] = len(config["second"])
    return counts


def ai_record(row: dict, dataset: str, provenance: dict) -> dict:
    """One item's AI record from its review item: agreed boxes, proposed spans; ai_validated only when both passes
    agree on every sampled box and the intervals carry no flicker or unclear flag."""
    from evalv2.datasets.records import new_record, promote_validated

    agreed = {str(r["second"]): r["box"] for r in row["boxes"] if r["status"] == "agree"}
    payload = {"clip": row["clip"], "kind": row["kind"], "item_id": row["item_id"], "boxes": agreed,
               "visible_spans": row["visible_spans"], "sampled_seconds": [r["second"] for r in row["boxes"]],
               "box_status": {str(r["second"]): r["status"] for r in row["boxes"]}, "interval_flags": row["flags"]}
    record = new_record(record_id=f"box:{row['clip']}:{row['item_id']}", dataset=dataset, kind="box", payload=payload,
                        clip=row["clip"], strata={"category": row["category"], "item_kind": row["kind"],
                                                  "half": row["half"]},
                        generator=provenance, flags=["validators_disagree"] if "box_disagreement" in row["flags"]
                        else [])
    checks = [{"name": "boxes_valid", "passed": all(boxes.valid_box(b) for b in agreed.values())},
              {"name": "boxes_agree", "passed": all(r["status"] in ("agree", "none_fits") for r in row["boxes"])},
              {"name": "intervals_clear", "passed": not {"flicker", "unclear", "no_interval_proposal"} & set(row["flags"])}]
    agrees = all(c["passed"] for c in checks)
    return promote_validated(record, checks=checks, validator={"id": f"{GEN_MODEL}:gen-box-validate-v1+"
                                                                     "gen-visibility-validate-v1", "agrees": agrees})


def build_records(args: argparse.Namespace) -> dict:
    """AI records for every item of the half; a complete primary review makes an item ``human_verified``;
    second reviews give the agreement report. Writes ``records/<half>/records.jsonl`` and ``agreement.json``."""
    import hashlib

    from evalv2.datasets.records import write_records

    review = args.out / "review" / args.half
    data = json.loads((review / "review-data.json").read_text(encoding="utf-8"))["items"]
    config = json.loads((review / "review-config.json").read_text(encoding="utf-8"))
    dataset = f"box-references-c3e-{args.half}-v1"
    provenance = {"model": GEN_MODEL, "prompts": {p: identity(p)["prompt_sha256"] for p in (
        "gen-box-select-v1", "gen-box-validate-v1", c3e.VISIBILITY_GENERATOR_PROMPT, c3e.VISIBILITY_VALIDATOR_PROMPT)},
        "sampler": c3e.SAMPLER_VERSION, "frame_limits_sha256": hashlib.sha256(
            (args.ra1 / "frame-limits-v1.json").read_bytes()).hexdigest()}
    records = {key: ai_record(row, dataset, provenance) for key, row in sorted(data.items())}
    primary, second, problems = {}, {}, []
    for path in sorted((review / "returns").glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        for key, decision in body["items"].items():
            entry = {**decision, "reviewer": body["reviewer"], "at": body["at"]}
            if body["mode"] == "primary":
                if config["primary"].get(data[key]["clip"]) != body["reviewer"]:
                    problems.append(f"{path.name}: {key} is not assigned to {body['reviewer']} as primary")
                    continue
                try:
                    records[key] = c3e_review.apply_review(records[key], data[key], entry, source_sha256=digest)
                    primary[key] = entry
                except (c3e_review.ReviewError, ValueError) as exc:
                    problems.append(f"{path.name}: {exc}"[:200])
            elif config["second"].get(key) == body["reviewer"]:
                second[key] = entry
            else:
                problems.append(f"{path.name}: {key} is not in {body['reviewer']}'s second-review sample")
    out = args.out / "records" / args.half
    ensure_private(out)
    out.mkdir(parents=True, exist_ok=True)
    digest = write_records(list(records.values()), out / "records.jsonl")
    ends = frame_ends(args.ra1)
    agreement = c3e_review.agreement(data, primary, second, {c: int(ends[c] - 1e-9) for c in ends})
    (out / "agreement.json").write_text(json.dumps(agreement, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tiers = {t: sum(r["tier"] == t for r in records.values()) for t in ("ai_proposed", "ai_validated",
                                                                        "human_verified")}
    return {"records": len(records), "records_sha256": digest, "tiers": tiers, "agreement": agreement,
            "problems": problems}


EXTRA_STATUSES = ("none_fits", "validator_only")  # the generator found no mark covering the item


def extra_localise(args: argparse.Namespace) -> dict:
    """The descriptive-query OWLv2 pass (v0.2 §2.1) on the seconds where the generator found no fitting mark, at
    the generator's and the validator's frame times; cached per clip under ``proposals-c3e-extra/`` (RA1's cache is
    read-only). Candidate coverage before and after is reported by kind."""
    import shlex

    from evalv2.core.hashing import canonical_json as cj
    from evalv2.references.detector import SubprocessDetector

    data = json.loads((args.out / "review" / args.half / "review-data.json").read_text(encoding="utf-8"))["items"]
    ends = frame_ends(args.ra1)
    cache = args.out / "proposals-c3e-extra"
    cache.mkdir(parents=True, exist_ok=True)
    need: dict[str, dict] = {}
    for row in data.values():
        item = {"clip": row["clip"], "kind": row["kind"], "item_id": row["item_id"], "text": row["text"],
                "query": c3e.items_for_query(row)}
        for r in row["boxes"]:
            if r["status"] in EXTRA_STATUSES:
                times = {float(r["second"])} | ({r["second"] + 0.5} if r["second"] + 0.5 < ends[row["clip"]] else set())
                entry = need.setdefault(row["clip"], {"times": set(), "queries": set()})
                entry["times"] |= times
                entry["queries"] |= set(c3e_v2.descriptive_queries(item))
    detector = None
    if args.detector_command:
        detector = SubprocessDetector(shlex.split(args.detector_command))
    done = []
    for clip, entry in sorted(need.items()):
        path = cache / f"{clip}.json"
        times, queries = sorted(entry["times"]), sorted(entry["queries"])
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if set(map(float, cached["frames"])) >= set(times) and set(cached["queries"]) >= set(queries):
                continue
            raise SystemExit(f"{path} holds other frames or queries; a changed extra pass is a new directory")
        if detector is None:
            raise SystemExit("--detector-command is needed for uncached clips")
        frames = {str(args.ra1 / "frames" / clip / f"t{t:08.3f}.jpg"): t for t in times}
        found = detector.propose(list(frames), queries)
        body = {"detector": dict(detector.identity), "queries": queries, "pass": "c3e-v0.2-descriptive",
                "frames": {f"{frames[p]:.3f}": [{"box": list(x.box), "score": x.score, "label": x.label} for x in rows]
                           for p, rows in found.items()}}
        path.write_bytes(cj(body))
        done.append(clip)
    return {"clips_needing_extra": len(need), "frames": sum(len(e["times"]) for e in need.values()),
            "ran": done, "coverage": extra_coverage(args, data)}


def _load_props(path: Path) -> dict:
    if not path.exists():
        return {}
    cached = json.loads(path.read_text(encoding="utf-8"))
    return {float(t): [boxes.Proposal(tuple(r["box"]), float(r["score"]), str(r.get("label", ""))) for r in rows]
            for t, rows in cached["frames"].items()}


def extra_coverage(args: argparse.Namespace, data: dict) -> dict:
    """Per kind: sampled generator frames with at least one candidate for the item, before (RA1) and after (RA1 plus
    the extra pass). A candidate is not evidence of localisation accuracy."""
    from collections import Counter

    before, after, total = Counter(), Counter(), Counter()
    for row in data.values():
        item = {"clip": row["clip"], "kind": row["kind"], "item_id": row["item_id"], "text": row["text"],
                "query": c3e.items_for_query(row)}
        ra1 = _load_props(args.ra1 / "proposals" / f"{row['clip']}.json")
        extra = _load_props(args.out / "proposals-c3e-extra" / f"{row['clip']}.json")
        for r in row["boxes"]:
            t = float(r["second"])
            total[row["kind"]] += 1
            before[row["kind"]] += bool(c3e_v2.union_proposals(ra1, {}, item, t))
            after[row["kind"]] += bool(c3e_v2.union_proposals(ra1, extra, item, t))
    return {k: {"frames": total[k], "with_candidate_before": before[k], "with_candidate_after": after[k]}
            for k in sorted(total)}


def _item_of(row: dict) -> dict:
    return {"clip": row["clip"], "kind": row["kind"], "item_id": row["item_id"], "text": row["text"],
            "query": c3e.items_for_query(row)}


def _answered(root: Path, packet_id: str, packet: dict) -> dict | None:
    """The answer of a FilePass packet (writing the packet when unanswered)."""
    fp = FilePass(root, {"model": GEN_MODEL})
    return fp.answer(packet_id, packet)


def box_tiers(args: argparse.Namespace) -> dict:
    """v0.2 §2.2–2.3: second-round packets where the extra pass added candidates to a "none fits" second, then the
    order-swapped adjudication of every non-consensus second; returns per item and second the box tier."""
    from collections import Counter

    half_ = args.half
    data = json.loads((args.out / "review" / half_ / "review-data.json").read_text(encoding="utf-8"))["items"]
    ends = frame_ends(args.ra1)
    r1 = args.out / "boxes" / half_
    r2 = args.out / "boxes2" / half_
    adj = args.out / "adjudication" / half_
    counts, tiers_by_kind, out = Counter(), {}, {}
    for key, row in sorted(data.items()):
        if not row["boxes"]:
            continue
        item, clip = _item_of(row), row["clip"]
        ra1 = _load_props(args.ra1 / "proposals" / f"{clip}.json")
        extra = _load_props(args.out / "proposals-c3e-extra" / f"{clip}.json")
        gp, ga = _answer(r1 / "generator", f"c3e-gen-{key}")
        vp, va = _answer(r1 / "validator", f"c3e-val-{key}")
        gen = boxes.boxes_by_second(gp["packet"], ga.get("answers", ga))
        val = boxes.boxes_by_second(vp["packet"], va.get("answers", va), offset_s=boxes.VALIDATOR_OFFSET_S)
        status = {r["second"]: r["status"] for r in row["boxes"]}
        again = [s for s in sorted(status) if status[s] in EXTRA_STATUSES
                 and len(c3e_v2.union_proposals(ra1, extra, item, float(s))) > len(c3e_v2.union_proposals(ra1, {}, item, float(s)))]
        if again:
            g_times = [float(s) for s in again]
            v_times = [t + 0.5 for t in g_times if t + 0.5 < ends[clip] - 1e-9]
            g2 = boxes.generator_packet(item, g_times, {t: c3e_v2.union_proposals(ra1, extra, item, t) for t in g_times},
                                        prompt_id="gen-box-select-v1")
            for frame in g2["frames"]:
                image = r2 / "images" / frame["image"]
                if not image.exists():
                    c3e.draw_marks(args.ra1 / "frames", clip, frame, image)
            g2a = FilePass(r2 / "generator", identity("gen-box-select-v1")).answer(f"c3e2-gen-{key}", g2)
            if g2a is None:
                counts["pending_round2_generator"] += 1
                continue
            v2p = boxes.validator_packet(item, v_times, {t: c3e_v2.union_proposals(ra1, extra, item, t) for t in v_times},
                                         prompt_id="gen-box-validate-v1")
            boxes.assert_blind(v2p, g2, g2a.get("answers", g2a))
            for frame in v2p["frames"]:
                image = r2 / "images" / frame["image"]
                if not image.exists():
                    c3e.draw_marks(args.ra1 / "frames", clip, frame, image)
            v2a = FilePass(r2 / "validator", identity("gen-box-validate-v1")).answer(f"c3e2-val-{key}", v2p)
            if v2a is None:
                counts["pending_round2_validator"] += 1
                continue
            gen.update(boxes.boxes_by_second(g2, g2a.get("answers", g2a)))
            got = boxes.boxes_by_second(v2p, v2a.get("answers", v2a), offset_s=boxes.VALIDATOR_OFFSET_S)
            for s in again:
                val[s] = got.get(s)
            counts["round2_items"] += 1
            counts["round2_seconds"] += len(again)
        per = {}
        for s in sorted(status):
            t = float(s)
            union = c3e_v2.union_proposals(ra1, extra, item, t)
            extra_only = [p for p in union if all(boxes.iou(p.box, q.box) < 0.9 for q in c3e_v2.union_proposals(ra1, {}, item, t))]
            best_extra = list(max(extra_only, key=lambda p: p.score).box) if extra_only else None
            cands = c3e_v2.candidates(gen.get(s), c3e_v2.map_box(val.get(s), union), best_extra)
            g, v = gen.get(s), val.get(s)
            consensus = g is not None and v is not None and boxes.iou(g, v) >= c3e_v2.AGREE_IOU
            adjudication = None
            if not consensus and cands:
                packets = c3e_v2.box_adjudication_packets(item, s, cands, "images")
                adjudication = {}
                for name, packet in packets.items():
                    if not (adj / "images" / packet["image"]).exists():
                        c3e_v2.render_adjudication(args.ra1 / "frames", clip, packet, adj, ends[clip])
                    answer = FilePass(adj / f"box-{name}", identity(c3e_v2.BOX_ADJ_PROMPT)).answer(
                        f"c3e-adj-{name}-{key}-{s:04d}", packet)
                    adjudication[name] = (packet, answer)
            res = c3e_v2.resolve_box(g, v, adjudication, bool(cands))
            per[str(s)] = res
            counts[f"tier_{res['tier']}"] += 1
            tiers_by_kind.setdefault(row["kind"], Counter())[res["tier"] if res["tier"] != "unresolved"
                                                             else f"unresolved: {res['reason']}"] += 1
        out[key] = per
    target = args.out / "tiers" / half_
    target.mkdir(parents=True, exist_ok=True)
    (target / "box-tiers.json").write_text(json.dumps(out, indent=0, sort_keys=True), encoding="utf-8")
    return {"counts": dict(counts), "by_kind": {k: dict(v) for k, v in sorted(tiers_by_kind.items())}}


def visibility_tiers(args: argparse.Namespace) -> dict:
    """v0.2 §2.4: order-swapped visibility adjudication packets for each item's non-consensus seconds (sampled box
    seconds first, when the half has a sampling), then the per-second visibility tier of every item."""
    from collections import Counter

    gt = load_gt_v1(data_root=args.data_root)
    ends = frame_ends(args.ra1)
    vis = args.out / "visibility"
    counts, by_kind, out = Counter(), {}, {}
    for name, clips in clips_of(args.half, gt).items():
        sampling_path = args.out / "boxes" / name / "sampling.json"
        sampling = json.loads(sampling_path.read_text(encoding="utf-8"))["sampling"] if sampling_path.exists() else {}
        tiers_path = args.out / "tiers" / name / "box-tiers.json"
        btiers = json.loads(tiers_path.read_text(encoding="utf-8")) if tiers_path.exists() else {}
        adj = args.out / "adjudication" / name
        for clip in clips:
            gpk, gans = _answer(vis / "generator", f"c3e-vis-gen-{clip}")
            vpk, vans = _answer(vis / "validator", f"c3e-vis-val-{clip}")
            G, V = c3e.visibility_votes(gpk["packet"], gans), c3e.visibility_votes(vpk["packet"], vans)
            last = int(ends[clip] - 1e-9)
            for item in c3e.items_for(gt, [clip]):
                key = f"{clip}-{item['item_id']}"
                entry = sampling.get(clip, {}).get(item["kind"])
                sampled = sorted(set(entry["anchors"]) | set(entry["decoys"])) if entry else []
                bt = btiers.get(key, {})
                box_consensus = {int(s) for s, r in bt.items() if r["tier"] == "consensus"}
                gv, vv = G[item["item_id"]], V[item["item_id"]]
                stored = adj / "vis-a" / "packets" / f"c3e-vadj-a-{key}.json"
                if stored.exists():  # the first pass already ran: reuse its seconds exactly (packets never change)
                    seconds = sorted({int(t) for sh in json.loads(stored.read_text())["packet"]["sheets"] for t in sh["tiles"]})
                else:
                    seconds = [s for s in c3e_v2.visibility_adjudication_seconds(gv, vv, last, sampled)
                               if s not in box_consensus]
                # Supplementary adjudication (v0.2 §2.4): sampled non-consensus seconds the first pass did not show.
                extra = sorted(s for s in sampled if s not in seconds and s not in box_consensus
                               and c3e_v2.visibility_consensus(gv, vv, s) is None)
                adjudicated = {}
                for prefix, secs, root in (("c3e-vadj", seconds, "images"), ("c3e-vadj2", extra, "images-supp")):
                    if not secs:
                        continue
                    packets = c3e_v2.visibility_adjudication_packets(item, secs, root)
                    answers = {}
                    for order, packet in packets.items():
                        for sheet in packet["sheets"]:
                            if not (adj / sheet["sheet"]).exists():
                                c3e_v2.render_visibility_sheet(args.ra1 / "frames", clip, sheet["tiles"], adj / sheet["sheet"])
                        answers[order] = FilePass(adj / f"vis-{order}", identity(c3e_v2.VIS_ADJ_PROMPT)).answer(
                            f"{prefix}-{order}-{key}", packet)
                    if all(a is not None for a in answers.values()):
                        adjudicated.update(c3e_v2.visibility_adjudicated(packets, answers))
                    else:
                        counts[f"pending_{prefix}"] += 1
                states = {s: c3e_v2.visibility_state(s, G[item["item_id"]], V[item["item_id"]], bt.get(str(s)),
                                                     adjudicated) for s in range(last + 1)}
                out[key] = {str(s): st for s, st in states.items()}
                for st in states.values():
                    tier = st["tier"] if st["tier"] != "unresolved" else "unresolved"
                    counts[f"seconds_{tier}"] += 1
                    by_kind.setdefault((name, item["kind"]), Counter())[tier] += 1
                counts["items"] += 1
                counts["items_adjudicated"] += bool(seconds)
                counts["items_supplementary"] += bool(extra)
        target = args.out / "tiers" / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "visibility-tiers.json").write_text(json.dumps({k: v for k, v in out.items()
                                                                  if k.split("-")[0] in clips}, sort_keys=True),
                                                      encoding="utf-8")
    return {"counts": dict(counts), "by_kind": {f"{h}/{k}": dict(v) for (h, k), v in sorted(by_kind.items())}}


def status(args: argparse.Namespace) -> dict:
    out = {}
    for root in sorted(p for p in args.out.rglob("packets") if p.is_dir()):
        answers = root.parent / "answers"
        out[str(root.parent.relative_to(args.out))] = {
            "packets": len(list(root.glob("*.json"))), "answers": len(list(answers.glob("*.json")))}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("visibility", "boxes", "review-build", "records", "extra-localise", "box-tiers",
                                    "visibility-tiers", "status"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--data-root", type=Path, default=Path("/home/hengz/evalv2-data"))
    ap.add_argument("--ra1", type=Path, default=None)
    ap.add_argument("--half", choices=("dev", "test", "all"), default="all")
    ap.add_argument("--run", type=Path, action="append", default=[])
    ap.add_argument("--reviewers", help="comma-separated team member ids for a new review configuration")
    ap.add_argument("--reassign", action="store_true", help="rebuild the review configuration")
    ap.add_argument("--detector-command", help="the OWLv2 runner command (extra-localise)")
    a = ap.parse_args()
    a.ra1 = a.ra1 or a.data_root / "v2" / "references" / "box-references-v1"
    ensure_private(a.out)
    a.out.mkdir(parents=True, exist_ok=True)
    if a.step == "boxes" and (a.half == "all" or not a.run):
        raise SystemExit("boxes needs one --half and at least one --run")
    if a.step in ("review-build", "records", "extra-localise", "box-tiers") and a.half == "all":
        raise SystemExit(f"{a.step} needs one --half")
    steps = {"visibility": visibility, "boxes": box_prepare, "review-build": review_build, "records": build_records,
             "extra-localise": extra_localise, "box-tiers": box_tiers, "visibility-tiers": visibility_tiers,
             "status": status}
    result = steps[a.step](a)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
