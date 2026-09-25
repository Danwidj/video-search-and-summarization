---
name: incident-start
description: Use to set up secrets and launch the incident profile from a laptop with start.sh, either fully local (mock-backend + vlm-gateway, zero GPU) or against the kwanz-ws VM over an SSH tunnel. Not for changing or repairing services on the VM itself - use incident-operate-vm.
license: Apache-2.0
metadata:
  version: "0.1.0"
  profile: "dev-profile-incident"
  tags: "incident startup local vm tunnel"
---
# Incident Start

`start.sh` is the single laptop entry point. It launches `incident-console-v2` on `http://localhost:3200` in both modes. Run everything below from `deploy/docker/developer-profiles/dev-profile-incident/`.

**Never** run `start.sh`, `.scripts/tunnel.sh` or `.scripts/tunnel-check.sh` on `kwanz-ws` itself. They are laptop-side only.

## Mode routing

| User says | Mode | Why |
|---|---|---|
| "run it locally", "no GPU", "frontend work", "offline from the VM" | `--mode local` | Mock VST/agent on `:7777` and the credential-holding gateway on `:8600`. SSH is never touched. |
| "run against the VM", "real agent", "full stack", "demo", no preference | `--mode vm` (default) | Real native `vss-agent` and VIOS on `kwanz-ws`. `start.sh` self-heals missing services. |

Details of each path: [`.docs/architecture.md` §2](../../.docs/architecture.md#2-deployment--connectivity).

## Prerequisites

1. **Tools:** `uv` and Node.js/npm on the laptop. For vm mode, add Tailscale (connected) and `ssh`.
2. **Secrets file:** `dev-profile-incident/.env.local`, which is untracked and supplied by the captain. Never commit it and never print its values. Check that it holds non-empty values for the names the services read:

   | Needed by | Variables |
   |---|---|
   | console, mock-backend, eval | `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` |
   | console, mock-backend, eval | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET` |
   | vlm-gateway (local mode) | `VLM_GATEWAY_API_KEY`, optional `VLM_GATEWAY_BASE_URL` |

   Check names only, without echoing values:
   ```bash
   for v in INCIDENT_SUPABASE_URL INCIDENT_SUPABASE_SERVICE_ROLE_KEY R2_ACCOUNT_ID R2_ACCESS_KEY R2_SECRET_KEY R2_BUCKET VLM_GATEWAY_API_KEY; do
     grep -q "^${v}=." .env.local && echo "ok      $v" || echo "MISSING $v"
   done
   ```
3. **Symlinks:** every service reads its own `.env.local`. Local mode reads `incident-console/.env.local` for the mock backend, so all four links are required:
   ```bash
   for d in incident-console incident-console-v2 vlm-gateway mock-backend; do ln -sfn ../.env.local "$d/.env.local"; done
   ```
   If you ran `.githooks/activate.sh` once for the clone, it keeps these links in sync across worktrees.
4. **vm mode only: SSH identity.** Set up `Host kwanz-ws` with `HostName` and your own `User` in `~/.ssh/config`, or export `VSS_SSH_USER` or `VSS_SSH_TARGET`. Resolution is non-interactive. See [`.docs/incident-profile-operations.md` §3](../../.docs/incident-profile-operations.md#3-laptop-to-vm-connectivity--ssh-troubleshooting).

## Instructions

```bash
./start.sh --mode local     # zero-GPU loop
./start.sh --mode vm        # VM backend (default when --mode is omitted)
```

The console runs in the foreground. Ctrl-C stops it, along with the backgrounded mock, gateway and tunnel.

Environment overrides such as `ENABLE_ANALYTICS`, `VSS_VM_IP`, `VSS_REPO_ROOT`, `INCIDENT_DOCKER_SERVICES` and `INCIDENT_NATIVE_SERVICES` are documented in the header of [`start.sh`](../../start.sh).

## Verify

| Check | local | vm |
|---|---|---|
| Console readiness: `curl -s localhost:3200/api/health` returns only booleans | yes | yes |
| Mock backend: `curl -s 127.0.0.1:7777/health` | yes | - |
| Gateway: `curl -s 127.0.0.1:8600/health` returns `{"status":"ok"}` | yes | - |
| Tunnel and agent: `./.scripts/tunnel-check.sh` or `curl -s localhost:8000/health` | - | yes |

In vm mode the console's health check leaves out gateway readiness. HTTP 503 from the VM for the first 60-90 s after a cold start is normal.

Then run one upload to report with [`incident-analyze-video`](../incident-analyze-video/SKILL.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `start.sh` aborts at the SSH preflight | Tailscale is disconnected or `Host kwanz-ws` is wrong. Test with `ssh -o BatchMode=yes kwanz-ws true`. |
| Logged in as the wrong VM user | Set `User` under `Host kwanz-ws`, or `export VSS_SSH_USER=<name>`. |
| Port 3200, 7777, 8000 or 8600 already in use | A previous run is still alive. Stop it, or find it with `lsof -i :<port>`. |
| Console health shows Supabase or R2 not configured | A missing variable or broken symlink. Re-run the prerequisite checks. |
| VM services missing after self-heal | Hand off to [`incident-operate-vm`](../incident-operate-vm/SKILL.md). |
