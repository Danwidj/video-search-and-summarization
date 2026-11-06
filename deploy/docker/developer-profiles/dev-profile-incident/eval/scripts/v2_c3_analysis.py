# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pre-registered end-to-end views and per-subject summaries from scored run directories (offline, deterministic).

View 1 contract validity (attempted = planned items), view 2 conditional on valid outputs, view 3 end-to-end usable
(a missing or invalid output is a failure; no severity error is imputed). Per-kind object counts for entities,
instruments and assets. 95% CIs: cluster bootstrap by clip, seed 20261027, 10,000 resamples.
Usage: python c3_analysis.py OUT_JSON RUN_DIR[:STAGE[:CLIPS_HALF:REPEATS]] ...
"""
import json, random, sys, collections
from pathlib import Path

SPLIT = json.loads(Path('/home/hengz/evalv2-data/ground_truth/ground-truth-v1.0/split-v2.json').read_text())
SCORE = 'scoring/evalv2-score-stage-v3/primary/live-videos.jsonl'
KINDS = ('entities', 'instruments', 'assets')


def boot(per_clip, f, seed=20261027, n=10000):
    """Ratio-of-sums bootstrap over clips: per_clip maps clip -> list of (num, den)."""
    keys = sorted(per_clip); rnd = random.Random(seed); vals = []
    for _ in range(n):
        num = den = 0.0
        for _ in keys:
            for a, b in per_clip[keys[rnd.randrange(len(keys))]]: num += a; den += b
        if den: vals.append(num / den)
    vals.sort()
    return [round(vals[int(.025 * len(vals))], 4), round(vals[int(.975 * len(vals)) - 1], 4)] if vals else None


def ratio(rows, clip_of, num, den):
    per = collections.defaultdict(list); N = D = 0.0
    for r in rows:
        a, b = num(r), den(r)
        if b: per[clip_of(r)].append((a, b)); N += a; D += b
    return {'numerator': round(N, 4), 'denominator': round(D, 4), 'value': round(N / D, 4) if D else None, 'ci95': boot(per, None) if D else None}


MODEL_OUTPUT = {'scored', 'contract_invalid', 'parse_failure'}


def combined_rows(run_dirs, stage):
    """Per work item one row: a model output from any run wins (it was never re-sent); otherwise the last run's row.
    Amendment A1 records (the crashed item, scored from its stored reply) are added as minimal invalid-output rows."""
    best = {}
    for run_dir in run_dirs:
        p = Path(run_dir) / SCORE
        if not p.exists():
            continue
        for r in (json.loads(l) for l in p.read_text().splitlines()):
            if r.get('stage', 'p1') != stage:
                continue
            k = (r['subject'], r['incident_id'], r['repeat']); old = best.get(k)
            if old is None or (old['outcome'] not in MODEL_OUTPUT):
                best[k] = r
        a = Path(run_dir) / 'amendment-a1-records.jsonl'
        if a.exists() and stage == 'p1':
            for x in (json.loads(l) for l in a.read_text().splitlines()):
                k = (x['subject'], x['item_id'], x['repeat'])
                best.setdefault(k, {'subject': x['subject'], 'incident_id': x['item_id'], 'repeat': x['repeat'], 'outcome': x['outcome'], 'amendment': 'A1'})
    return list(best.values())


def summarise(run_dirs, stage, half, repeats):
    rows = combined_rows(run_dirs if isinstance(run_dirs, (list, tuple)) else [run_dirs], stage)
    clips = SPLIT[half]; out = {}
    for subj in sorted({r['subject'] for r in rows}):
        got = {(r['incident_id'], r['repeat']): r for r in rows if r['subject'] == subj}
        planned = [(c, k) for c in clips for k in range(1, repeats + 1)]
        att = [got.get(p) for p in planned]
        valid = [r for r in att if r and r['outcome'] == 'scored']
        clip = lambda r: r['incident_id']
        def t_ok(r): return 1.0 if r and r['outcome'] == 'scored' and (r['incident_field_scores'].get('type') or {}).get('pass') else 0.0
        def sev(r):
            s = (r or {}).get('incident_field_scores', {}).get('severity_level') or {}
            return None if s.get('expected') is None or s.get('predicted') is None else abs(float(s['predicted']) - float(s['expected']))
        e2e = [(p[0], r) for p, r in zip(planned, att)]
        res = {'planned': len(planned), 'rows': len(got), 'outcomes': dict(collections.Counter((r['outcome'] if r else 'no_output') for r in att)),
               'validity': ratio([(p[0], r) for p, r in zip(planned, att)], lambda x: x[0], lambda x: 1.0 if x[1] and x[1]['outcome'] == 'scored' else 0.0, lambda x: 1.0),
               'cond_type_accuracy': ratio(valid, clip, lambda r: t_ok(r), lambda r: 1.0 if (r['incident_field_scores'].get('type') or {}).get('expected') else 0.0),
               'cond_severity_mae': ratio(valid, clip, lambda r: sev(r) or 0.0, lambda r: 1.0 if sev(r) is not None else 0.0),
               'e2e_type_accuracy': ratio(e2e, lambda x: x[0], lambda x: t_ok(x[1]), lambda x: 1.0),
               'usable_severity_rate': ratio(e2e, lambda x: x[0], lambda x: 1.0 if x[1] and x[1]['outcome'] == 'scored' and sev(x[1]) is not None and sev(x[1]) <= 1 else 0.0, lambda x: 1.0)}
        for k in KINDS:
            def tp(r, k=k): return float(r[k]['counts']['tp'])
            def gt(r, k=k): return float(len(r['ground_truth'][k]))
            def pr(r, k=k): return float(r[k]['counts']['tp'] + r[k]['counts']['fp'])
            res[f'{k}_cond_recall'] = ratio(valid, clip, tp, gt)
            res[f'{k}_cond_precision'] = ratio(valid, clip, tp, pr)
            res[f'{k}_e2e_recall'] = ratio(e2e, lambda x: x[0], lambda x, k=k: tp(x[1]) if x[1] and x[1]['outcome'] == 'scored' else 0.0,
                                           lambda x, k=k: float(GT_COUNTS[k].get(x[0], 0)))
        out[subj] = res
    return out


GT = json.loads(Path('/home/hengz/evalv2-data/ground_truth/ground-truth-v1.0/ground_truth.json').read_text())['sheets']
def _iid(r): return r.get('Incident_ID (P_key, F_key)') or r.get('Incident_ID (P_key)')
GT_COUNTS = {k: collections.Counter(_iid(r) for r in GT[f'gt_{k}']) for k in KINDS}

if __name__ == '__main__':
    out = {}
    for spec in sys.argv[2:]:
        parts = spec.split(':'); runs = parts[0].split('+'); stage = parts[1] if len(parts) > 1 else 'p1'
        half = parts[2] if len(parts) > 2 else 'test'; reps = int(parts[3]) if len(parts) > 3 else 2
        out['+'.join(Path(r).name for r in runs) + f':{stage}'] = summarise(runs, stage, half, reps)
    Path(sys.argv[1]).write_text(json.dumps(out, indent=1)); print(json.dumps({k: {s: {m: v[m]['value'] if isinstance(v.get(m), dict) else v.get(m) for m in ('planned', 'rows', 'validity', 'cond_type_accuracy', 'cond_severity_mae', 'e2e_type_accuracy', 'usable_severity_rate')} for s, v in x.items()} for k, x in out.items()}, indent=1))


def _f1(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0; r = tp / (tp + fn) if tp + fn else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def paired(rows_a, rows_b, seed=20261027, n=10000):
    """Pre-registered paired comparison A - B on (clip, repeat) items both scored validly; clip-cluster bootstrap,
    two-sided p = 2 min(share <= 0, share >= 0). Metrics: type accuracy, severity MAE, object score (mean of entity F1
    and pooled instrument+asset F1, computed from pooled counts per resample)."""
    A = {(r['incident_id'], r['repeat']): r for r in rows_a if r['outcome'] == 'scored'}
    B = {(r['incident_id'], r['repeat']): r for r in rows_b if r['outcome'] == 'scored'}
    keys = sorted(set(A) & set(B)); clips = sorted({k[0] for k in keys})
    def sev(r):
        s = r['incident_field_scores'].get('severity_level') or {}
        return None if s.get('expected') is None or s.get('predicted') is None else abs(float(s['predicted']) - float(s['expected']))
    def metrics(ks):
        out = {}
        t = [(1.0 if (A[k]['incident_field_scores'].get('type') or {}).get('pass') else 0.0) - (1.0 if (B[k]['incident_field_scores'].get('type') or {}).get('pass') else 0.0) for k in ks if (A[k]['incident_field_scores'].get('type') or {}).get('expected')]
        out['type_accuracy'] = sum(t) / len(t) if t else None
        sv = [sev(A[k]) - sev(B[k]) for k in ks if sev(A[k]) is not None and sev(B[k]) is not None]
        out['severity_mae'] = sum(sv) / len(sv) if sv else None
        def obj(R):
            c = {kind: [0, 0, 0] for kind in ('entities', 'objects')}
            for k in ks:
                for kind in ('entities', 'instruments', 'assets'):
                    cc = R[k][kind]['counts']; tgt = c['entities' if kind == 'entities' else 'objects']
                    tgt[0] += cc['tp']; tgt[1] += cc['fp']; tgt[2] += cc['fn']
            return (_f1(*c['entities']) + _f1(*c['objects'])) / 2
        out['object_score'] = obj(A) - obj(B)
        return out
    point = metrics(keys); by = {c: [k for k in keys if k[0] == c] for c in clips}
    rnd = random.Random(seed); samples = collections.defaultdict(list)
    for _ in range(n):
        ks = [k for _ in clips for k in by[clips[rnd.randrange(len(clips))]]]
        for m, v in metrics(ks).items():
            if v is not None: samples[m].append(v)
    res = {'paired_items': len(keys), 'clips': len(clips)}
    for m, v in point.items():
        s = sorted(samples[m])
        res[m] = None if v is None or not s else {'diff': round(v, 4), 'ci95': [round(s[int(.025 * len(s))], 4), round(s[int(.975 * len(s)) - 1], 4)],
                                                 'p': round(min(1.0, 2 * min(sum(x <= 0 for x in s), sum(x >= 0 for x in s)) / len(s)), 4)}
    return res


def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i]); adj = [0.0] * len(ps); run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i])); adj[i] = round(run, 4)
    return adj
