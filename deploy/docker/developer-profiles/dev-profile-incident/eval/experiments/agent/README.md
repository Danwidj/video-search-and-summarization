# Local experiment agent (VSS arm)

A minimal local `vss-agent` for the prompt experiments (plan decision D14 (b)). It serves only `POST /api/v1/incidents/{id}/analyze` with the `incident_report_gen` tool, on `127.0.0.1:8765`. The shared VM agent is never used for experiments, and must never set `INCIDENT_EXPERIMENTS_ENABLED`.

| File | What |
|---|---|
| `experiment-agent.yml` | NAT config: the incident tool only. No VST, RTVI or tracing |
| `start-experiment-agent.sh` | Starts it with `env -i` and only the model endpoint, its key and `INCIDENT_EXPERIMENTS_ENABLED=1`. There is no Supabase, database or R2 setting, so nothing is persisted and no image is uploaded. It refuses if `services/agent/.env_file` exists (the agent would load it) |
| `fake_upstream.py` | A local stand-in for the model endpoint, so the agent and the VSS arm can be checked at no cost |

```bash
# No-cost check (two terminals), from eval/:
python3 experiments/agent/fake_upstream.py --port 8899
NAT_BIN=<agent venv>/bin/nat experiments/agent/start-experiment-agent.sh --upstream http://127.0.0.1:8899
uv run python scripts/eval_experiment_plumbing.py --agent-url http://127.0.0.1:8765   # VSS arm over real HTTP

# Real endpoint (paid calls happen only when a run sends requests):
NAT_BIN=<agent venv>/bin/nat experiments/agent/start-experiment-agent.sh
```

**Checked on 2026-10-27 with the fake upstream:**
- `/health` responds.
- An experimental request returns `revision_id: null`, `persisted: false`, the prompt id and SHA-256, `p1_elapsed_ms` and `usage`.
- The plumbing run's C2 scored 25/25 through it. C3 failed 25/25, as designed: the agent refuses a prompt that is not in the committed registry.

**Cropping (option (a)):** an experimental crops-on request crops into a fresh in-memory store, discarded after the request, so detection and box calls run with no disk or R2 write (`experiment.evidence_store`). An agent with R2 settings still refuses it (409). The box calls are paid and the runner cannot count them in advance, so a crop pilot needs its own authorisation and bound ([decision record](../../../.docs/mvp2/experiment-decision-record.md#stage-0-pilot-authorised-blocked-on-pricing)).
