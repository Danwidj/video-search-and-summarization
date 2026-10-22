---
name: incident-start
description: Use to set up secrets and launch the incident profile from a laptop with start.sh, either fully local (mock-backend + vlm-gateway, zero GPU) or against the kwanz-ws VM over an SSH tunnel. Not for changing or repairing services on the VM itself - use incident-operate-vm.
license: Apache-2.0
metadata:
  version: "0.1.2"
  profile: "dev-profile-incident"
  tags: "incident startup local vm tunnel"
---
# Incident Start

`start.sh` is the single laptop entry point. It launches `incident-console-v2` on `http://localhost:3200` in both modes. Run everything below from `deploy/docker/developer-profiles/dev-profile-incident/`.

**Never** run `start.sh`, `.scripts/tunnel.sh` or `.scripts/tunnel-check.sh` on `kwanz-ws` itself. They are laptop-side only.

## Mode routing

| User says | Mode | Why |
|---|---|---|
| "run it locally", "no GPU", "frontend work", "offline from the VM" | `--mode mock` | Mock VST/agent on `:7777` and the credential-holding gateway on `:8600`. SSH is never touched. `--mode local` still works as a deprecated alias. |
| "run against the VM", "real agent", "full stack", "demo", no preference | `--mode vm` (default) | Real native `vss-agent` and VIOS on `kwanz-ws`. `start.sh` self-heals missing services: it starts stopped ones, pulls missing images, clones a missing checkout, and fails with a reason instead of hanging. |

Details of each path: [`.docs/architecture.md` §2](../../.docs/architecture.md#2-deployment--connectivity).

## Prerequisites

1. **Tools:** `uv` and Node.js/npm on the laptop. For vm mode, add Tailscale (connected) and `ssh`.
2. **Secrets file:** `dev-profile-incident/.env.local`, which is untracked and supplied by the captain. Never commit it and never print its values. Check that it holds non-empty values for the names the services read:

   | Needed by | Variables |
   |---|---|
   | console, mock-backend, eval | `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` (the **finals** project) |
   | eval, database scripts | `INCIDENT_DB_DSN` (finals session pooler, port 5432) |
   | console, mock-backend, eval | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET` |
   | vlm-gateway (mock mode) | `VLM_GATEWAY_API_KEY`, optional `VLM_GATEWAY_BASE_URL` |

   Check names only, without echoing values:
   ```bash
   for v in INCIDENT_SUPABASE_URL INCIDENT_SUPABASE_SERVICE_ROLE_KEY R2_ACCOUNT_ID R2_ACCESS_KEY R2_SECRET_KEY R2_BUCKET VLM_GATEWAY_API_KEY; do
     grep -q "^${v}=." .env.local && echo "ok      $v" || echo "MISSING $v"
   done
   ```
3. **Symlinks:** every service reads its own `.env.local`; local mode passes `mock-backend/.env.local` to the mock backend and `vlm-gateway/.env.local` to the gateway, and stops with the fix command if either is missing. All three links are required:
   ```bash
   for d in incident-console-v2 vlm-gateway mock-backend; do ln -sfn ../.env.local "$d/.env.local"; done
   ```
   If you ran `.githooks/activate.sh` once for the clone, it keeps these links in sync across worktrees. It never overwrites an existing `.env.local` copy, so a worktree made before the finals switch still holds the midterm values: refresh it.

   The Supabase values must name the finals project. Midterm (`rfevukimyftzbxlehwel`) is a frozen read-only record ([`.docs/architecture.md`](../../.docs/architecture.md#two-supabase-projects-one-per-phase)). Mock mode passes these credentials to the mock backend too, and its analyse route writes `mock-run-*` rows into that database.
4. **vm mode only: SSH identity.** Set up `Host kwanz-ws` with `HostName` and your own `User` in `~/.ssh/config`, or export `VSS_SSH_USER` or `VSS_SSH_TARGET`. Resolution is non-interactive. See [`.docs/incident-profile-operations.md` §3](../../.docs/incident-profile-operations.md#3-laptop-to-vm-connectivity--ssh-troubleshooting).

## Instructions

```bash
./start.sh --mode mock      # zero-GPU loop
./start.sh --mode vm        # VM backend (default when --mode is omitted)
./start.sh --mode vm --no-console   # VM side only: backend + tunnel, no Next.js console
./start.sh --mode vm --keep-backend # leave VM services running when this run exits
```

The console runs in the foreground. Ctrl-C stops it, along with the backgrounded mock, gateway and tunnel. In vm mode, exiting also stops the VM backend services (`vss-agent` and Docker containers in-place via `docker stop`, never removed) if this run was the last active session on `kwanz-ws`. To opt out and leave the backend up, pass `--keep-backend` or set `VSS_STOP_ON_LAST_EXIT=false`.

Environment overrides such as `ENABLE_ANALYTICS`, `VSS_VM_IP`, `VSS_REPO_ROOT`, `INCIDENT_DOCKER_SERVICES` and `INCIDENT_NATIVE_SERVICES` are documented in the header of [`start.sh`](../../start.sh). In vm mode `VSS_VM_IP` is detected from the VM over SSH when unset (fallback `10.131.1.5`); set it only to force an address.

## Verify

| Check | local | vm |
|---|---|---|
| Console readiness: `curl -s localhost:3200/api/health` returns only booleans | yes | yes |
| Mock backend: `curl -s 127.0.0.1:7777/health` | yes | - |
| Search route (always-on): `curl -s -X POST 127.0.0.1:7777/api/v1/incidents/search -H "Content-Type: application/json" -d '{"query":"test","top_k":1}'` | yes | - |
| Chat route: `curl -s -X POST 127.0.0.1:7777/api/v1/incidents/chat -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"test"}]}'` | yes | - |
| Gateway: `curl -s 127.0.0.1:8600/health` returns `{"status":"ok"}` | yes | - |
| Tunnel, agent, proxy and search: `./.scripts/tunnel-check.sh` or `curl -s localhost:8000/health` | - | yes |

In vm mode the console's health check leaves out gateway readiness. HTTP 503 from the VM for the first 60-90 s after a cold start is normal.

Then run one upload to report with [`incident-analyze-video`](../incident-analyze-video/SKILL.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `start.sh` aborts at the SSH preflight | Read the `Cause:` / `Fix:` lines it prints (Tailscale logged out or stopped, VM offline in the tailnet, DNS, SSH timeout or refused, login rejected, host key changed). Table: [`.docs/incident-profile-operations.md` §3](../../.docs/incident-profile-operations.md#3-laptop-to-vm-connectivity--ssh-troubleshooting). |
| `start.sh` stops with `[vm] ERROR` or "timed out" | The Docker step on the VM failed: exit 10 repo, 11 `generated.env.remote` missing, 12 docker unusable, 13 image pull (NGC login), 14/124 `compose up` failed or stuck (its output shows container states and Kafka logs). Tunables: `VSS_PULL_TIMEOUT`, `VSS_COMPOSE_UP_TIMEOUT`, `VSS_NATIVE_START_TIMEOUT`. |
| Tunnel step fails | `start.sh` says whether a laptop port is taken, the SSH forward is blocked (or `VSS_AGENT_HOST` on the VM is bound to a LAN address instead of `127.0.0.1`), the VM address is wrong (set `VSS_VM_IP`), or the agent or proxy is down on the VM. |
| Logged in as the wrong VM user | Set `User` under `Host kwanz-ws`, or `export VSS_SSH_USER=<name>`. |
| Port 3200, 7777, 8000 or 8600 already in use | A previous run is still alive. Stop it, or find it with `lsof -i :<port>`. |
| Console health shows Supabase or R2 not configured | A missing variable or broken symlink. Re-run the prerequisite checks. |
| Saving, editing or verifying fails with "permission denied" while reads work | `.env.local` still points at the frozen midterm project. Set the 3 finals values (and refresh other worktrees' copies). |
| VM services missing after self-heal | Hand off to [`incident-operate-vm`](../incident-operate-vm/SKILL.md). |
