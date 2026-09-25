---
name: incident-operate-vm
description: Use to deploy, restart, inspect, debug or tear down the incident backend on the kwanz-ws VM - native services (vss-agent, analytics) via native-services.sh, Docker appliances (VIOS, HAProxy, Redis, Kafka) via compose, generated.env.remote, and the agent editable reinstall. Not for the laptop launch (use incident-start) and never via NVIDIA's dev-profile.sh / vss-deploy-profile.
license: Apache-2.0
metadata:
  version: "0.1.0"
  profile: "dev-profile-incident"
  tags: "incident vm operations native docker troubleshooting"
---
# Incident Operate VM

`kwanz-ws` is a **shared** team workstation. Every action here affects teammates.

Canonical facts: [`.docs/incident-profile-operations.md`](../../.docs/incident-profile-operations.md) (topology, runbook, verification) and [`.docs/status.md` §4](../../.docs/status.md#4-live-vm-configuration-snapshot-kwanz-ws) (live env snapshot).

## Never

| Never | Why | Instead |
|---|---|---|
| `deploy/docker/scripts/dev-profile.sh down` (or `up`) for this profile | `down` runs `docker compose down -v` and wipes `VSS_DATA_DIR`, including about 35 GB of cached model weights. `dev-profile.sh` does not know the `incident` profile. | `./.scripts/down.sh` or plain `docker compose -p mdx down` |
| `.scripts/rebuild.sh` without the captain's go-ahead | Full stock-profile rebuild that also wipes the weight cache | `./.scripts/rebuild-svc.sh <service>` |
| Start the `vss-agent` Docker container | The native agent already owns `:8000` ("no double agent") | `./.scripts/native-services.sh restart vss-agent` |
| `uv sync` in `services/agent` on the VM | `nvdataset` resolves only from NVIDIA's internal artifactory | The reinstall procedure below |
| `_type: nim` for remote models, or a `*_BASE_URL` ending in `/v1` | `nim_langchain` leaks `verify_ssl` into the request body (HTTP 400), and clients append `/v1` themselves | `_type: openai`, bare host URL |

**Ask first:** stopping services teammates may be using, editing `generated.env.remote`, pruning images, or running `.scripts/clean-datalog.sh`.

## Service split

| Kind | Services | Manage with |
|---|---|---|
| Native (fast restart, about 2 s) | `vss-agent` :8000; optional `video-analytics-api` :8081 and `behavior-analytics` (`ENABLE_ANALYTICS=true`) | `.scripts/native-services.sh start\|stop\|restart\|status\|logs <svc\|all\|analytics>` |
| Docker appliances | VIOS (`vss-vios-*`), `vss-haproxy-ingress` :7777, `redis`, `phoenix`, `kafka`; optional `elasticsearch`; MVP2 `vss-rtvi-*` | `docker compose -p mdx ...` with `generated.env.remote` |

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
| Pick up agent code changes (`services/agent/src`) | `git pull` in `/srv/rise-up/vss`, then `./native-services.sh restart vss-agent` |
| Pick up `generated.env.remote` changes | `./native-services.sh restart vss-agent`. Env is captured at process start; check it in `/proc/<pid>/environ`. |
| Tail logs | `./logs.sh vss-agent` (native) or `./logs.sh <container>` (Docker) |
| Refresh one service | `./rebuild-svc.sh <service>`: restarts native services, rebuilds and recreates Docker ones |
| Start missing appliances | From `deploy/docker`: `docker compose -f compose.yml -f developer-profiles/dev-profile-incident/compose.override.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote --scale init-dirs=0 --scale render-config=0 --scale wdm-env-from-config=0 --scale sdr-controller=0 up -d <services>` |
| Stop everything safely | `./down.sh` (native stop + `compose down --remove-orphans`, no `-v`) |
| Load NGC credentials | `source ./ngc-env.sh` |

A full deploy from nothing is easiest from the laptop: `./start.sh --mode vm` deploys fresh or self-heals a partial state.

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
- `HOST_IP=10.131.1.5` and `EXTERNAL_IP=localhost`.
- `VSS_AGENT_CONFIG_FILE` points at the **dev-profile-base** config. The search config lacks `report_agent`.
- `REPORT_REFERENCE_BASE_DIR` is set (for example `/tmp`).
- `STREAM_PROCESSOR_HTTP_PORT=10000`.
- `LLM_MODEL_TYPE=openai` and `VLM_MODEL_TYPE=openai`, with bare Brev URLs.

## Troubleshooting order

1. `./status.sh` and `./native-services.sh status`: is it running?
2. `./health.sh`: is the agent up? A 503 in the first 60-90 s of a cold start is normal.
3. `./logs.sh vss-agent`, `docker logs --tail 100 vss-haproxy-ingress`, `docker logs --tail 100 vss-vios-ingress`.
4. Partial deploy: start only the missing service. Don't force-redeploy over inconsistent state.

Note: `sdr-controller` was removed from the incident deployment stack (unused and port-clashes with streamprocessing on port 10000; see [`.docs/decisions.md`](../../.docs/decisions.md)); it should not be running.

## After changing anything

If you changed a port, service, env rule or script, update [`.docs/incident-profile-operations.md`](../../.docs/incident-profile-operations.md). If the live config changed, also update the [`.docs/status.md`](../../.docs/status.md) snapshot, in the same PR.
