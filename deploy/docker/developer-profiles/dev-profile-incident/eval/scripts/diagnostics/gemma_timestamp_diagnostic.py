"""Owner-approved 2026-11-02: Gemma 4 31B timestamp/frame-label diagnostic. 3 dev-only calls, <= 0.1M tokens, <= $0.01.

Same video delivery as the C1e pilot (presigned R2 GET URL), OpenRouter pinned to Crusoe, strict JSON schema.
Asks what the model received; never touches the official C1e outputs. Run from eval/ with the eval venv.
"""
import json, os, sys
from pathlib import Path
from dotenv import dotenv_values
sys.path.insert(0, os.getcwd())
from evalv2.adapters.openai_compat import ENDPOINTS, OpenAICompatAdapter
from evalv2.adapters.registry import capabilities_for
from evalv2.adapters.base import CallContext
from evalv2.core.artifacts import ArtifactStore
from evalv2.core.budget import BudgetLedger, Cap
from evalv2.core.retry import POLICIES
from evalv2.clips import r2_signer
from evalv2.executor import load_manifest_clips

OUT = Path('/home/hengz/evalv2-data/v2/diagnostics/gemma-timestamps')
ENVF = '/home/hengz/video-search-and-summarization/deploy/docker/developer-profiles/dev-profile-incident/.env.local'
for k, v in dotenv_values(ENVF).items():
    if v and not os.environ.get(k): os.environ[k] = v
CLIPS = ('RoadAccidents017', 'Burglary093', 'Explosion029')  # dev only: 8.1 s, 25.4 s, 80.3 s
dev = set(json.loads(Path('eval_reproducibility/split-v2.json').read_text())['dev'])
assert set(CLIPS) <= dev, 'dev clips only'
PROMPT = ("Answer only from what you were given, not from what the video probably shows. "
          "1) How many separate still frames of this video did you receive? "
          "2) Were the frames labelled with timestamps (for example 00:05 or 0:05)? If yes, write the label of the FIRST "
          "frame and the label of the LAST frame exactly as written. If there were no labels, write 'none'. "
          "3) How long, in seconds, do you think the whole video is, and how did you decide?")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["frames_received", "timestamp_labels_present", "first_label", "last_label", "estimated_duration_s", "basis"],
          "properties": {"frames_received": {"type": "integer"}, "timestamp_labels_present": {"type": "boolean"}, "first_label": {"type": "string"},
                         "last_label": {"type": "string"}, "estimated_duration_s": {"type": "number"}, "basis": {"type": "string"}}}
MODEL = 'google/gemma-4-31b-it'
routing = {"provider": {"order": ["Crusoe"], "allow_fallbacks": False, "data_collection": "deny", "require_parameters": True}}
adapter = OpenAICompatAdapter('diag-gemma', MODEL, ENDPOINTS['openrouter'], capabilities_for(MODEL), extra_body=routing)
OUT.mkdir(parents=True, exist_ok=True)
ledger = BudgetLedger([Cap('inference', max_attempts=3, max_tokens=100_000)], OUT / 'budget.jsonl')
store = ArtifactStore(OUT / 'store')
sign = r2_signer()
keys = {c['incident_id']: (c['r2_key'], c['duration_seconds']) for c in load_manifest_clips()}
done = {json.loads(l)['clip'] for l in (OUT / 'results.jsonl').read_text().splitlines()} if (OUT / 'results.jsonl').exists() else set()
for clip in CLIPS:
    if clip in done:
        continue
    key, dur = keys[clip]
    body = {"model": MODEL, "messages": [{"role": "user", "content": [{"type": "video_url", "video_url": {"url": sign(key, 3600)}}, {"type": "text", "text": PROMPT}]}],
            "temperature": 0.0, "max_tokens": 1024, "response_format": {"type": "json_schema", "json_schema": {"name": "diag", "schema": SCHEMA, "strict": True}}}
    ctx = CallContext(store=store, ledger=ledger, policy=POLICIES['none'], subject='gemma-diagnostic', task='diagnostic', tokens_bound=30_000)
    res = adapter.complete(body, ctx)
    u = res.usage
    row = {"clip": clip, "duration_s": dur, "ok": res.ok, "failure": res.failure.kind if res.failure else None, "reply": res.text if res.ok else None,
           "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens,
           "request_ref": str(res.request_ref), "response_ref": str(res.response_ref) if res.response_ref else None}
    with (OUT / 'results.jsonl').open('a') as fh:
        fh.write(json.dumps(row) + '\n')
    print(json.dumps({k: row[k] for k in ('clip', 'duration_s', 'ok', 'failure', 'reply', 'prompt_tokens', 'total_tokens')}))
