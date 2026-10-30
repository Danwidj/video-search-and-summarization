# Ground-truth review (PR 3 → PR 4 → PR 5)

> **Status:** PR 3 built the review workbook (`v0.1`, 184 findings). PR 4 added the AI-assisted correction and the candidate workbook (`Ground Truth Candidate v0.2.xlsx`; see [Correction and candidate (PR 4)](#correction-and-candidate-pr-4)). Nothing here is ground truth until PR 5 freezes it after the final annotations are approved.

This folder holds the **proposed** corrections to the human-labelled ground truth. They follow [`annotation-guidelines-v1.0`](../annotation-guidelines-v1.0.md) and are **not final ground truth**:
- PR 4 reviews each proposal (AI-assisted and human), setting it to Approved or Rejected;
- PR 5 freezes the approved version as `ground-truth-v1.0`.

| File | In git | What |
|---|---|---|
| `Ground Truth Review v0.1.xlsx` | **no** (see Storage) | The editable working workbook: the source's sheets with the proposed values written in, plus `Review Summary` and `Change Log` |
| [`audit-v0.1.md`](audit-v0.1.md) | yes | The audit report: findings by rule, with ids and counts only and no annotation text |
| [`review-v0.1-manifest.json`](review-v0.1-manifest.json) | yes | Source SHA-256, output SHA-256, change-log digest, counts and inventory facts |
| `Ground Truth Candidate v0.2.xlsx` | **no** | The PR 4 candidate: verified corrections applied, AI video-review proposals listed as Pending, v0.1 decisions carried forward. Review continues here |
| `ai-proposals-v0.2.jsonl` | **no** | The AI reviewer's proposals (they quote annotation text) |
| [`candidate-v0.2.md`](candidate-v0.2.md), [`candidate-v0.2-manifest.json`](candidate-v0.2-manifest.json) | yes | Candidate report (ids and counts only) and its hashes, digests and counts |
| `Ground Truth Review Package <version>.xlsx`, `review-overrides-<v>.json` | **no** | The human review package and its local overrides ([below](#human-review-package)) |

## Source

`Complete Ground Truth Labelling.xlsx` (profile root, gitignored) is never modified. The build opens it twice, once for values and once for formulas, saves only the new file, and fails if the source's SHA-256 changes. The v0.1 source SHA-256 is:

`7c3f1fcc186e2608887ea31fc9eda06178522c4525763f69d7e2b46032cc2a5c`

## Rebuild

From `eval/`:

```bash
uv run python scripts/gt_review_build.py                 # source: ../Complete Ground Truth Labelling.xlsx, version v0.1
uv run python scripts/gt_review_build.py --version v0.2  # a new version; never overwrite one under review
```

The same source, dataset manifest and generator always give the same change-log digest (recorded in the manifest). The `.xlsx` bytes differ between builds because the file embeds its save time, so compare digests, not file hashes.

**A rebuild never silently replaces a workbook** (`review_backup.guard_overwrite`):

| Existing workbook of the same version | Result |
|---|---|
| none | built |
| present, no review decisions | **refused** unless `--overwrite`; with it, a backup is taken first |
| present, with review decisions (any status other than Pending, or a reviewer or notes) | **refused**, even with `--overwrite`; only `--overwrite --discard-review-decisions` replaces it, after a backup |
| open in Excel (`~$` lock file present) | **refused** |

A refused build writes nothing: not the workbook, the manifest or the audit report. New proposals go into a new version (`--version v0.2`). Carrying v0.1's decisions forward into a new version is a PR 4 tool, not a rebuild.

## The working workbook

- **`Review Summary`** (first sheet): progress, entries by class and by rule, and the affected videos. All counts are formulas over the `Change Log`, so they update as reviewers work.
- **`Change Log`:** one row per finding, with these columns:
  - change id, incident and record id, sheet, row and field;
  - original and proposed values;
  - class, rule, guideline reference and reason;
  - **supporting video evidence** (the clip, its local copy and the incident window to watch);
  - confidence and **review status** (Pending / Approved / Rejected dropdown), reviewer and notes.
- **Data sheets** (`gt_incidents`, `gt_entities`, `gt_instruments`, `gt_assets`): the source columns, rows, ids and formulas, with proposed values written in.
  - **Colours:** green marks verified corrections, yellow rule-based proposals, orange cells needing video review.
  - **Cell comments** give the change id and the original value.
  - **Two review columns** follow the documented ones: `review_flags` and `change_ids`.
  - **Removals:** rows proposed for removal are struck through and flagged, not deleted.
  - **Additions:** new records are appended with the next free id, and nothing is renumbered.
- **Classes:**
  - `verified_correction`: provable without video, from the workbook or the dataset manifest;
  - `rule_based_proposal`: an approved guideline rule applied to what the annotator recorded;
  - `needs_video_review`: only the video can answer, so **no value is proposed**;
  - `informational`: recorded, no change.
- **Out of taxonomy:** possible out-of-taxonomy clips carry the `OUT_OF_TAXONOMY_CANDIDATE` review flag. Their type stays one of the five categories.

## Correction and candidate (PR 4)

From `eval/`:

```bash
uv run python scripts/gt_review_packet.py      # per-video review packets: the annotation and its findings (eval_data/, gitignored)
uv run --no-project --python 3.12 --script scripts/gt_frames.py eval_data/gt_review_packets/index.json  # timestamped contact sheets
# AI review: follow ../correction_prompts/gt-correction-v1.0.md, write ai-proposals-<version>.jsonl here
uv run python scripts/gt_candidate_build.py --version v0.2   # candidate workbook + candidate-v0.2.md + manifest
uv run python scripts/gt_review_backup.py snapshot --kind Candidate --version v0.2 --reason "..."
```

- **Video evidence.** `gt_frames.py` runs in its own throwaway environment with OpenCV, so OpenCV is not an eval dependency. Each contact sheet tile has its video time burned in. Window sheets cover the incident window ±10 s at 1 frame/s, and the overview sheet has 12 frames across the clip. `frames.json` records every tile time and each sheet's SHA-256, so cited evidence can be checked against the exact image (about 34 MB for 38 videos, under `eval_data/gt_frames/`).
- **Inputs are independent of the system under test.** Packets hold only the human annotation (without annotator names), the findings and the clip. `guard_inputs` refuses anything under `eval_data/results/`, `contracts/experiments/`, `eval/experiments/` or `eval_reproducibility/runs/`.
- **AI proposals** (`gt-correction-v1.0`): one per finding, with `decision` (`propose_change`, `keep_original` or `uncertain`), the proposed value, an explanation, evidence tiles, a confidence and full provenance (model, prompt SHA-256, frame SHA-256s). `validate_proposal` rejects any proposal that cites a tile that does not exist, comes from a changed sheet, lacks evidence or repeats the original. A rejected proposal is shown with its problems and can never be applied.
- **What the candidate applies:**

  | Entry | Status in the candidate | Applied to the data sheets |
  |---|---|---|
  | `verified_correction` that passes the independent re-check (`verify_mechanical`, not the audit's rule code) | `Auto-verified` | yes |
  | `verified_correction` that fails it | `Pending` | no |
  | `rule_based_proposal`, and every AI proposal | `Pending` | **no**, until a person sets `Approved` |
  | an entry a person set `Approved` (in this or the prior workbook) | `Approved` | yes: the proposed value, or the `Accepted value` when filled in. Approving a review entry without a proposed value confirms the original |
  | an entry a person set `Rejected` | `Rejected` | no (a reviewer may also reject an `Auto-verified` entry) |

- **Decisions are carried forward, never discarded.** The build reads the prior workbook's status, reviewer, notes and accepted value. It refuses if that workbook describes different findings, never writes to it, and checks the SHA-256 of both the prior workbook and the source before and after. A candidate that holds human decisions is never overwritten; review more and build the next version (`--prior "…Candidate v0.2.xlsx" --version v0.3`).
- **Linked entries are decided together.** A reclassification (R10) removes an instrument and adds an asset; approving only one half is reported as a problem.
- **The corrected records** come from `apply_to_records`: the source's documented columns plus only the applied entries. Each record keeps `_source_row` and `_change_ids` for provenance, and the same inputs always give the same `records_sha256`. PR 5 freezes from these records, not from cell formatting.

## Human review package

`scripts/gt_review_package.py` turns a candidate's Pending entries into a review package. It is a new workbook, `Ground Truth Review Package <version>.xlsx`, where decisions are recorded, plus a local HTML companion with the cited evidence tiles. It never overwrites a file, never approves anything, and carries decisions forward from an earlier package (`--prior-package`).

```bash
uv run python scripts/gt_review_package.py --candidate "ground_truth/review/Ground Truth Candidate v0.2.xlsx" \
    --version v0.2.1 --prior-package "ground_truth/review/Ground Truth Review Package v0.2.xlsx"
uv run python scripts/gt_review_backup.py snapshot --kind Review --version "Package v0.2.1" --reason "before session 1"
# after review:
uv run python scripts/gt_candidate_build.py --prior "ground_truth/review/Ground Truth Review Package v0.2.1.xlsx" --version v0.3
```

**Contents:**
- **Change Log:** every Pending row, grouped by incident and correction type, with before and after values, evidence, AI confidence, a recommendation, flags and a suggested accepted value. Then the Auto-verified rows, greyed. These are exactly the columns `gt_candidate_build.py --prior` reads.
- **Read me:** the review workflow and the traceability checks.
- **By incident:** a per-incident summary.

**Flags:**

| Flag | Meaning |
|---|---|
| `UNCERTAIN` | The AI could not decide |
| `PRONOUN: P1 violation` | A neutral description is followed by a gendered pronoun. A correction is suggested |
| `PRONOUN: permitted under P1` | Fine if the qualified identification is visually supported |
| `HIGH IMPACT` | A scored severity or threat, a taxonomy status, or an item classification |

**Overrides:** `review-overrides-<version>.json` (local, gitignored, because it quotes annotation text) holds the suggested pronoun fixes and case-specific recommendations.

**Current state (2026-10-28):** the 98 entries are adjudicated into **`Ground Truth AI-Adjudicated Candidate v0.3.xlsx`** ([below](#ai-assisted-adjudication-2026-10-28)), awaiting the owner's approval. **Package v0.2.2:** `Ground Truth Review Package v0.2.2.xlsx` (built from Candidate v0.2.1), with the P1 flags. **`Filename` is a protected field** (decision 2026-10-28): the 24 `_demo` filename entries (R01) are informational, never applied, and listed with the grey rows. Packages v0.2 and v0.2.1 and Candidate v0.2 are superseded and unchanged, and hold no decisions.

## AI-assisted adjudication (2026-10-28)

The owner authorised AI-assisted adjudication of the 98 Pending entries (`.docs/mvp2/resolve-ground-truth-proposals.md`, a local document not tracked in Git):
- **Instructions:** [`gt-adjudication-v1.0`](../correction_prompts/gt-adjudication-v1.0.md).
- **Close-up tool:** `scripts/gt_frame_detail.py`, for any time range at any frame rate, enlarged.
- **Records:** `ai-adjudication-v0.3.jsonl` (local, gitignored).

```bash
uv run python scripts/gt_candidate_build.py --prior "ground_truth/review/Ground Truth Review Package v0.2.2.xlsx" \
    --proposals ground_truth/review/ai-proposals-v0.2.jsonl --adjudication ground_truth/review/ai-adjudication-v0.3.jsonl \
    --version v0.3     # -> Ground Truth AI-Adjudicated Candidate v0.3.xlsx + candidate-v0.3.md
uv run python scripts/gt_freeze.py --candidate "ground_truth/review/Ground Truth AI-Adjudicated Candidate v0.3.xlsx" \
    --proposals ground_truth/review/ai-proposals-v0.2.jsonl --adjudication ground_truth/review/ai-adjudication-v0.3.jsonl
```

- **Every adjudication is validated:**
  - a decision consistent with the earlier proposal;
  - a final value valid for its field;
  - video verified, with cited tiles that exist (a close-up for high impact);
  - provenance and prompt SHA-256 present.
- **An invalid adjudication is never applied.** The statuses are `AI-*`, the Reviewer stays empty, and a later human decision overrides any of them.
- **The candidate's Change Log** shows, per entry: the decision, final value, impact, video verified, uncertain, justification, evidence and provenance.

## Backups (local, versioned)

The review decisions exist only in the working workbook, so every reviewed state is kept as an immutable local copy:

```bash
uv run python scripts/gt_review_backup.py snapshot --reason "before review session 1"
uv run python scripts/gt_review_backup.py snapshot --reason "after review session 1"
uv run python scripts/gt_review_backup.py list      # time, file, SHA-256, decisions, reason
uv run python scripts/gt_review_backup.py verify    # every logged backup still matches its SHA-256
```

- **Where:** `eval/ground_truth/review/backups/Ground Truth Review v0.1 <UTC time> <sha8>.xlsx`, gitignored like the workbook. A backup is never overwritten: a second one in the same second gets ` (2)`.
- **Log:** `backups/backup-log.jsonl` has one line per backup: time, file, SHA-256, size, reason, and the review state (status counts, entries with a reviewer or notes). It holds no annotation text.
- **When:** before and after every review session, and automatically before any permitted rebuild overwrite.
- **Restore:** copy a backup over the working file after taking a snapshot of the current one. Check it with `verify`, and its decisions with `list`.
- **Retention:** keep every backup (about 220 KB each).
- **Durability today: one machine only.** The working file and its backups share the WSL disk. A second local copy (for example under `/mnt/c/Users/<you>/Documents/gt-review-backups/`, outside the WSL disk image) protects against losing the WSL distribution but not the machine. Durable shared storage is the R2 proposal below, which needs approval first.

## Storage

The working workbook is **not committed**. `eval/.gitignore` lists it on purpose, with this README as the reason:
- the source workbook has never been committed (`eval/eval_data/` is ignored as real annotation data);
- the workbook carries annotator names (`Labelled_By`);
- where the frozen ground truth will live (plan decision D7) is not yet decided.

**Persistence today:** the file is at `eval/ground_truth/review/Ground Truth Review v0.1.xlsx` on the build machine. Its SHA-256 at build time is in `review-v0.1-manifest.json`, and it can be rebuilt with the same change-log digest from the source, the tracked dataset manifest and the generator.

**Proposed durable location (needs approval; a write to shared storage):** the private R2 bucket under `ground-truth/review/<version>/`, holding the workbook, the manifest and the source's SHA-256. R2 already holds the dataset and is backed up with it. Each reviewed state is uploaded as a new object (`…-reviewed-<date>.xlsx`), never overwritten. A team drive would also work; R2 keeps it next to the videos and under the same access control.
