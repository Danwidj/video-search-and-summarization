---
name: incident-operate-vm
description: Use to deploy, restart, inspect, debug or tear down the incident backend on the kwanz-ws VM - native services (vss-agent, analytics) via native-services.sh, Docker appliances (VIOS, HAProxy, Redis, Kafka) via compose, generated.env.remote, and the agent editable reinstall. Not for the laptop launch (use incident-start) and never via NVIDIA's dev-profile.sh / vss-deploy-profile.
license: Apache-2.0
metadata:
  version: "0.1.1"
  profile: "dev-profile-incident"
  tags: "incident vm operations native docker troubleshooting"
---
# Incident Operate VM

`kwanz-ws` is a **shared** team workstation. Every action here affects teammates.

Canonical facts: [`.docs/incident-profile-operations.md`](../../.docs/incident-profile-operations.md) (topology, runbook, verification) and [`.docs/status.md` §6](../../.docs/status.md#6-live-vm-configuration-kwanz-ws) (live env snapshot).

## Never

| Never | Why | Instead |
|---|---|---|
| `deploy/docker/scripts/dev-profile.sh down` (or `up`) for this profile | `down` runs `docker compose down -v` and wipes `VSS_DATA_DIR`, including about 35 GB of cached model weights. `dev-profile.sh` does not know the `incident` profile. | `./.scripts/down.sh` or plain `docker compose -p mdx stop` (or `docker compose -p mdx down --remove-orphans` for a clean slate, still never `-v`) |
| Start the `vss-agent` Docker container | The native agent already owns `:8000` ("no double agent") | `./.scripts/native-services.sh restart vss-agent` |
| `uv sync` in `services/agent` on the VM | `nvdataset` resolves only from NVIDIA's internal artifactory | The reinstall procedure below |
| `_type: nim` for remote models, or a `*_BASE_URL` ending in `/v1` | `nim_langchain` leaks `verify_ssl` into the request body (HTTP 400), and clients append `/v1` themselves | `_type: openai`, bare host URL |

**Ask first:** stopping services teammates may be using, editing `generated.env.remote`, pruning images, or running `.scripts/clean-datalog.sh`.

## Service split

| Kind | Services | Manage with |
|---|---|---|
| Native (fast restart, about 2 s) | `vss-agent` :8000; optional `video-analytics-api` :8081 and `behavior-analytics` (`ENABLE_ANALYTICS=true`) | `.scripts/native-services.sh start\|stop\|restart\|status\|logs <svc\|all\|analytics>` |
| Docker appliances | VIOS (`vss-vios-*`), `vss-haproxy-ingress` :7777, `redis`, `phoenix`, `kafka`; optional `elasticsearch` | `docker compose -p mdx ...` with `generated.env.remote` |

Full port and rationale table: [operations §2](../../.docs/incident-profile-operations.md#2-native-vs-docker-service-split).

## Instructions

Paths on the VM: repo `/srv/rise-up/vss`, scripts `/srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.scripts`.

### 1. Inspect before acting

```bash
ssh kwanz-ws
cd /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.scripts
./status.sh                       # docker compose -p mdx ps + native status
./health.sh                       # agent :8000/health
./gpu.sh                          # nvidia-smi
```

### 2. Common operations

| Goal | Command |
|---|---|
| Pick up agent code changes (`services/agent/src`) | `git pull` in `/srv/rise-up/vss`, then `./native-services.sh restart vss-agent`. The incident contract (`vss_agents/incident_contract/`) is vendored from `contracts/` and synchronised via `contracts/sync.py`. It is package data in the editable install, so a restart picks it up; it adds no dependencies. |
| Pick up `generated.env.remote` changes | `./native-services.sh restart vss-agent`. Env is captured at process start; check it in `/proc/<pid>/environ`. |
| Tail logs | `./logs.sh vss-agent` (native) or `./logs.sh <container>` (Docker) |
| Refresh one service | `./rebuild-svc.sh <service>`: restarts native services, rebuilds and recreates Docker ones |
| Start missing appliances | From `deploy/docker`: `docker compose -f compose.yml -f developer-profiles/dev-profile-incident/compose.override.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d <services>` |
| Stop everything safely | `./down.sh` (native stop + `docker compose -p mdx stop`, no `-v`). Containers and data are kept; restart is `./start.sh --mode vm`. Exited orphan containers are no longer cleaned up by `down.sh`; use manual `docker compose -p mdx down --remove-orphans` when a clean slate is wanted (still never `-v`). Stack appliances use `unless-stopped` via `compose.override.yml`, so stopped containers stay stopped across VM reboots. |
| Load NGC credentials | `source ./ngc-env.sh` |
| Populate or refresh search evidence (`evidence_crops`) | In `/srv/rise-up/vss`: `set -a; . deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote; set +a; services/agent/.venv/bin/python scripts/backfill_official_timestamps.py --dry-run`, then rerun without `--dry-run` (add `--concurrency 2`; the Brev gateway rate-limits at 4). Idempotent: it skips rows already present. All model calls are remote (Brev VLM, NVIDIA-hosted embeddings). Restart `vss-agent` afterwards only if `services/agent/src` changed. |

A full deploy from nothing is easiest from the laptop: `./start.sh --mode vm` deploys fresh or self-heals a partial state (clones a missing checkout, fixes a stale `HOST_IP` in `generated.env.remote` with a backup, pulls missing images, bounded `compose up`; see `.scripts/vm-ensure-docker.sh`).

### 3. Agent editable reinstall

Needed when `vss_agents` is not an editable install, so code changes don't take effect:

```bash
cd /srv/rise-up/vss/services/agent
uv pip install --python .venv/bin/python --no-deps --index-url https://pypi.org/simple -e .
uv pip install --python .venv/bin/python supabase opencv-python-headless setuptools
cd /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.scripts && ./native-services.sh restart vss-agent
```

Verify that `.venv/lib/python3.13/site-packages/vss_agents-*.dist-info/direct_url.json` has `"editable": true`.

### 4. `generated.env.remote` rules

The file is untracked and lives on the VM only. Rules (why for each: [operations §5](../../.docs/incident-profile-operations.md#5-vm-deployment-configuration-principles-generatedenvremote)):

- `VSS_APPS_DIR` and `VSS_DATA_DIR` are absolute paths.
- `HOST_IP` set to the VM's internal LAN IP (currently `10.132.56.251`, previously `10.131.1.5`; `vm-ensure-docker.sh` updates stale entries automatically) and `EXTERNAL_IP=localhost`.
- `VSS_AGENT_CONFIG_FILE` points at the **dev-profile-base** config. The search config lacks `report_agent`.
- `REPORT_REFERENCE_BASE_DIR` is set (for example `/tmp`).
- `STREAM_PROCESSOR_HTTP_PORT=10000`.
- `LLM_MODEL_TYPE=openai` and `VLM_MODEL_TYPE=openai`, with bare Brev URLs.
- Search embeddings use the NVIDIA-hosted endpoint with `NVIDIA_API_KEY` (or `NGC_CLI_API_KEY`) from this file; the Brev key cannot call `/v1/embeddings`. Override with `EVIDENCE_EMBEDDING_BASE_URL`, `EVIDENCE_EMBEDDING_MODEL`, `EVIDENCE_EMBEDDING_API_KEY`. The loader and the search route must use the same model.
- `incident_report_gen` reads `VLM_BASE_URL` + `VLM_NAME` (P1), `LLM_BASE_URL` (RP1; the model comes from the contract) and `OPENAI_API_KEY`. Changing `VLM_NAME` changes the agent-mode P1 model; ask first.
- `VSS_AGENT_HOST` defaults to `127.0.0.1` (loopback only: the agent has no auth and holds the DB admin key). An old `VSS_AGENT_HOST=0.0.0.0` must be removed or set to `127.0.0.1`.
- `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` name the **finals** Supabase project, never the frozen midterm one. The native `vss-agent` (search, chat, standalone persistence), the evidence loader and `native-services.sh` read them. To switch: back up the file, set the two values, `./native-services.sh restart vss-agent`, then check the host (never the key) in `/proc/<pid>/environ` and that a search adds a row to finals `queries` (the agent only warns when it cannot record one). Steps and rollback: [`incident-manage-database`](../incident-manage-database/SKILL.md#build-finals-and-switch-over-once). Finals uses an `sb_secret_...` server key, which is not a JWT, and the agent connects through `supabase-py`, whose version on the VM is not pinned (`pyproject.toml` requires only `supabase~=2.0`; `uv.lock` has no entry). Older 2.x releases reject non-JWT keys with `Invalid API key`. **Before switching**, run the one-row connection test in the agent's own environment ([VM key check](../incident-manage-database/SKILL.md#build-finals-and-switch-over-once), step 4):
  ```bash
  cd /srv/rise-up/vss
  read -rp 'finals URL: ' FINALS_URL; read -rsp 'finals sb_secret key: ' FINALS_KEY; echo; export FINALS_URL FINALS_KEY
  services/agent/.venv/bin/python -c "import os, importlib.metadata as m, supabase; c = supabase.create_client(os.environ['FINALS_URL'], os.environ['FINALS_KEY']); print('supabase', m.version('supabase'), 'ok, rows', len(c.table('videos').select('id').limit(1).execute().data))"
  unset FINALS_KEY
  ```
  If it fails with `Invalid API key` or a JWT error, run `uv pip install --python services/agent/.venv/bin/python -U 'supabase>=2,<3'` (ask first: shared VM) and retest. The evidence loader (`scripts/backfill_official_timestamps.py`) uses the same venv and `incident_db.get_db()`, so the same test covers it. Pinning a minimum `supabase` version in `services/agent` is a follow-up.
- GPU allocation: all Docker appliances and native services pinned strictly to GPU 0 (`CUDA_VISIBLE_DEVICES=0`, `NVIDIA_VISIBLE_DEVICES=0`, `RT_CV_DEVICE_ID=0`, `RT_EMBED_DEVICE_ID=0`, `FIXED_SHARED_DEVICE_IDS=0`) to protect GPU 1 for co-tenants.

## Troubleshooting order

1. `./status.sh` and `./native-services.sh status`: is it running?
2. `./health.sh`: is the agent up? A 503 in the first 60-90 s of a cold start is normal.
3. `./logs.sh vss-agent`, `docker logs --tail 100 vss-haproxy-ingress`, `docker logs --tail 100 vss-vios-ingress`.
4. Partial deploy: start only the missing service. Don't force-redeploy over inconsistent state.

Note: `sdr-controller` was removed from the incident deployment stack (unused and port-clashes with streamprocessing on port 10000; see [`.docs/decisions.md`](../../.docs/decisions.md)); it should not be running.

## After changing anything

If you changed a port, service, env rule or script, update [`.docs/incident-profile-operations.md`](../../.docs/incident-profile-operations.md). If the live config changed, also update the [`.docs/status.md`](../../.docs/status.md) snapshot, in the same PR.
