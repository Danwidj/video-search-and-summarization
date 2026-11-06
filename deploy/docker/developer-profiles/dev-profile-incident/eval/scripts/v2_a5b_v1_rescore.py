# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3 amendment A5-b (owner-approved 2026-11-04): V1 Stage 3 Super replies re-scored with C3's frozen scorer.

Builds a run directory in the executor's own format (store, checkpoint, prediction records) from V1's stored raw
replies of `s3-c1-direct-base` (+ its recovery), each reply passed through C3's policy (`v1.evaluate_policy`, with
amendment A1) exactly as `IncidentObjectsTask` does, then the standard `python -m evalv2 score --offline` scores it.
LABEL: "V1 historical Super observation (re-scored)". It is NOT a C3 run: V1 harness and retry path, 1 repeat,
2026-10-29/30, results already published in V1. Run with the A5 eval checkout (frozen scorer) as the working dir:
    cd /home/hengz/vss-wt-c3a5/.../eval && uv run --frozen python /home/hengz/evalv2-data/v2/runs/c3/a5b_v1_rescore.py OUT
"""
import dataclasses, json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
from evalv2.core.artifacts import ArtifactStore
from evalv2.core.checkpoint import Checkpoint
from evalv2.tasks.base import PredictionRecord, WorkItem
from evalv2.tasks.incident_objects import v1

V1 = Path('/home/hengz/video-search-and-summarization/deploy/docker/developer-profiles/dev-profile-incident/eval/eval_data/results/experiments')
SUBJECT, TASK = 'super-direct-v1-historical', 'incident_objects'
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
if (out / 'checkpoint.jsonl').exists():
    sys.exit('refused: run directory exists (append-only)')
main = json.load(open(V1 / 's3-c1-direct-base/20261029T124321Z/results.json'))
rec = json.load(open(V1 / 's3-c1-direct-base-recovery/20261030T064627Z/results.json'))
by = {v['incident_id']: ('main', v) for v in main['videos']}
for v in rec['videos']:
    if v['outcome'] == 'scored':
        by[v['incident_id']] = ('v1-recovery', v)
manifest = json.load(open('eval_reproducibility/dataset-manifest-v1.json'))
dur = {c['incident_id']: float(c['duration_seconds']) for c in manifest['clips']}
store = ArtifactStore(out / 'store'); cp = Checkpoint(out / 'checkpoint.jsonl'); sources = {}
for clip, (src, v) in sorted(by.items()):
    item = WorkItem(task=TASK, subject=SUBJECT, item_id=clip, repeat=1, spec={'model': v['model_id']}) \
        if 'spec' in WorkItem.__dataclass_fields__ else WorkItem(task=TASK, subject=SUBJECT, item_id=clip, repeat=1)
    raw = v['p1_raw'] or {}
    prov = {'source': f"V1 {main['experiment_id']} ({src})", 'model': v['model_id'], 'run_id': v['run_id'],
            'harness_git_sha': main['harness_git_sha'], 'prompt_id': v.get('prompt_id')}
    if raw.get('ok') and raw.get('content') is not None:
        policy = v1.evaluate_policy(raw['content'], dur.get(clip))
        prediction = policy['report'] if policy['core_ok'] else v1.empty_prediction()
        validation = {'core_violations': policy['core'], 'enrichment_violations': policy['enrichment'],
                      'full_contract_ok': policy['full_contract_ok'], 'core_ok': policy['core_ok']}
        pref = store.put('prediction', {'raw': raw['content'], 'finish_reason': raw.get('finish_reason'),
                                        'validation': validation, 'prediction': prediction})
        record = PredictionRecord(item.key, TASK, SUBJECT, clip, 1,
                                  outcome=v1.outcome({'ok': True, 'core_ok': policy['core_ok']}, validation),
                                  prediction_ref=str(pref), usage=raw.get('usage'), timing=v.get('timing'), provenance=prov)
    else:
        kind = raw.get('failure_kind') or v['outcome']
        record = PredictionRecord(item.key, TASK, SUBJECT, clip, 1, outcome=v1.outcome(raw, {}),
                                  failure={'kind': kind, 'detail': str(raw.get('error'))[:200]}, usage=raw.get('usage'),
                                  timing=v.get('timing'), provenance=prov)
    ref = store.put('prediction-record', dataclasses.asdict(record))
    cp.record(item.key, record.outcome, ref=str(ref), failure_kind=record.failure_kind, subject=SUBJECT, item_id=clip,
              repeat=1, prediction_ref=record.prediction_ref)
    sources[clip] = {'source': src, 'outcome': record.outcome}
(out / 'a5b-provenance.json').write_text(json.dumps({'label': 'V1 historical Super observation (re-scored); NOT a C3 run',
    'v1_records': ['s3-c1-direct-base/20261029T124321Z', 's3-c1-direct-base-recovery/20261030T064627Z'],
    'scorer_checkout': os.getcwd(), 'items': sources}, indent=1))
print(json.dumps({'items': len(sources), 'outcomes': {o: sum(1 for s in sources.values() if s['outcome'] == o)
                                                     for o in {s['outcome'] for s in sources.values()}}}))
