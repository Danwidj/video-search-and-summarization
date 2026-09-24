# Lifecycle scripts (in `.scripts/`)

The old `mdx-*` shell aliases / `ngc-env-on` / `gpu` from
[`deploy/docker/developer-profiles/dev-profile-incident/.dotfiles/`](../.dotfiles/README.md) moved here as standalone,
executable scripts, ready to run individually. Since the native split (see the profile README's
"Native vs. Docker Service Split"), the VM-side scripts cover both halves: native processes through
`native-services.sh`, Docker appliance containers through `docker compose -p mdx`.

| Script                            | Was                         | Runs on    | What it does                                                                                                                                                                                                    |
| --------------------------------- | --------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `../start.sh`                     | — (new)                     | **laptop** | One-command daily entry point (lives in the parent `dev-profile-incident/`): checks the VM backend deploy state over SSH, deploys fresh if nothing is running, starts missing services when the state is partial, opens the tunnel in the background, then runs incident-console-v2 |
| `.scripts/tunnel.sh`              | `mdx-tunnel-incident`       | **laptop** | Open the SSH tunnel to the kwanz-ws backend in the foreground (agent 8000, NIMs 30081/30082, ingress 7777; Ctrl-C closes it)                                                                                   |
| `.scripts/tunnel-check.sh`        | `mdx-tunnel-incident-check` | **laptop** | Prove the tunnel from the laptop end (agent health + NIM ports)                                                                                                                                                 |
| `.scripts/resolve-ssh-target.sh`  | — (new)                     | **laptop** | Sourced by `start.sh` / `tunnel.sh`: resolves `VSS_SSH_TARGET` (`VSS_SSH_TARGET`, else `VSS_SSH_USER`, else a 5 s prompt pre-filled from `~/.ssh/config` `User` or `$USER`; host from `VSS_SSH_HOST`, default `kwanz-ws`) |
| `.scripts/native-services.sh`     | — (new)                     | VM         | `start`/`stop`/`restart`/`status [--porcelain]`/`logs` for the native services (`vss-agent`, `video-analytics-api`, `behavior-analytics`; `all` / `analytics` shorthands). PID files and logs under `<repo>/.run/` (`VSS_RUN_DIR` overrides) |
| `.scripts/status.sh`              | `mdx-ps`                    | VM         | `docker compose -p mdx ps`, then `native-services.sh status`                                                                                                                                                    |
| `.scripts/down.sh`                | `mdx-down`                  | VM         | `native-services.sh stop`, then `docker compose -p mdx down --remove-orphans` — **no `-v`** (preserves the ~35 GB model-weight cache — never run `dev-profile.sh down`)                                        |
| `.scripts/health.sh`              | `mdx-health`                | laptop/VM  | Agent health probe on `:8000/health`                                                                                                                                                                            |
| `.scripts/logs.sh`                | `mdx-logs`                  | VM         | Tail one service's logs (default `vss-agent`): native services via `native-services.sh logs`, anything else via `docker logs -f`                                                                               |
| `.scripts/disk.sh`                | `mdx-disk`                  | VM         | `docker system df -v`                                                                                                                                                                                           |
| `.scripts/rebuild-svc.sh`         | `mdx-rebuild-svc`           | VM         | Fast per-service refresh: native services are restarted (`native-services.sh restart`); Docker services are rebuilt (`docker compose up -d --build --force-recreate` with the active `generated.env*`)         |
| `.scripts/rebuild.sh`             | `mdx-rebuild`               | VM         | Full stock-profile rebuild via `dev-profile.sh up` (interactive confirmation; wipes the model-weight cache)                                                                                                     |
| `.scripts/prune-native-images.sh` | — (new)                     | VM         | Remove the Docker images (and leftover containers) of the services that now run natively; asks for confirmation if `services/agent/.venv/bin/nat` is missing                                                  |
| `.scripts/clean-datalog.sh`       | `mdx-clean-datalog`         | VM         | Data-dir cleanup between deploys (requires passwordless sudo)                                                                                                                                                   |
| `.scripts/ngc-env.sh`             | `ngc-env-on`                | VM         | `source ./ngc-env.sh` to export the shared NGC credentials (`/srv/rise-up/.ngc_env`; `VSS_NGC_ENV` overrides)                                                                                                   |
| `.scripts/gpu.sh`                 | `gpu`                       | VM         | One-shot `nvidia-smi` status                                                                                                                                                                                    |

## Laptop-side scripts & start.sh modes

`tunnel.sh`, `tunnel-check.sh`, and top-level `start.sh` are **laptop-side only** (SSH tunnel from developer laptops to the `kwanz-ws` backend); never run them on `kwanz-ws` itself.

`start.sh` (at the top level of `dev-profile-incident/`) is the laptop-side one-command daily entry point for **incident-console-v2** (it no longer launches the Streamlit v1 console — see [`../incident-console/README.md`](../incident-console/README.md) for that):
- **Modes:** Accepts `--mode local|vm` (or `VSS_START_MODE` env var, default `vm`) to select the backend.
  - **`vm` mode:** Checks the remote deployment state on `kwanz-ws` over SSH (deploying fresh if nothing is running, starting missing services for a partial deploy), opens the background SSH tunnel, and exports `ANALYSIS_MODE=agent`.
  - **`local` mode:** Skips SSH, starts `mock-backend` (127.0.0.1:7777) and `vlm-gateway` (127.0.0.1:8600) locally with `--env-file .env.local`, and exports `ANALYSIS_MODE=gateway`.
- **Frontend execution:** Both modes launch `incident-console-v2` via `npm run dev -- --port 3200`.
- **Process cleanup:** A cleanup trap stops local background processes on exit.
