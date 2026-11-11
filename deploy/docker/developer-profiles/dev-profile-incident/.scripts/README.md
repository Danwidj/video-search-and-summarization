# Lifecycle scripts

Shell scripts that start, check and stop the incident backend. The laptop-side scripts open and check the SSH tunnel; the VM-side scripts run the native services and Docker appliances on the VM. [start.sh](../start.sh) calls most of them for you.

## What is inside

| Script | Runs on | What it does |
|---|---|---|
| [../start.sh](../start.sh) | laptop | Entry point: checks and heals the VM backend, opens the tunnel, runs the console |
| `tunnel.sh` | laptop | Opens the SSH tunnel in the foreground (Ctrl-C closes it) |
| `tunnel-check.sh` | laptop | Checks the tunnel: agent health and the search route |
| `vm-preflight.sh` | laptop | Sourced by `start.sh` and `tunnel.sh`: SSH target and probe, VM address, cause of a failure |
| `vm-ensure-docker.sh` | VM, piped by `start.sh` | Bounded Docker deploy: clone, env check, `HOST_IP` fix, pull, `compose up` |
| `native-services.sh` | VM | `start`, `stop`, `restart`, `status` and `logs` for the native services |
| `media-tools.sh` | VM, run by `native-services.sh` | `install` and `check` for `ffmpeg` and `ffprobe`: a SHA-256-checked static build in `<repo>/.tools/ffmpeg/bin` unless both are on `PATH` |
| `tracker-models.sh` | VM, run by `native-services.sh` | `install` and `check` for the NanoTrack `.onnx` files of object tracking, fetched into `<repo>/.tools/tracker-models` |
| `tracking-stack.sh` | VM, started by `start.sh` unless `ENABLE_TRACKING=false` | `start`, `stop`, `status` and `restart-perception` for the person-tracking stack |
| `status.sh` | VM | Containers, native services and `nvidia-smi` |
| `down.sh` | VM | Stops native services and containers without removing them |
| `health.sh` | laptop or VM | Probes the agent on `:8000/health` |
| `logs.sh` | VM | Tails one service's logs (default `vss-agent`) |
| `rebuild-svc.sh` | VM | Restarts a native service, or rebuilds one Docker service with the profile overrides |
| `test-env-template.sh` | laptop | Hermetic check of `.env` (sources cleanly, defined above use, no secrets) and `compose.unused.env` |
| `ngc-env.sh` | VM | `source` it to export the shared NGC credentials |
| [prune-native-images.sh](../skills/incident-operate-vm/scripts/prune-native-images.sh) | VM | Removes the Docker images of services that now run natively |
| `test-*.sh` | any | Tests for `native-services.sh`, `vm-preflight.sh`, `vm-ensure-docker.sh` and `prune-native-images.sh` |

## Rules

- Run `start.sh`, `tunnel.sh` and `tunnel-check.sh` on the laptop only, never on the VM.
- Never run `down.sh` with `-v`, and never run `dev-profile.sh down` for this profile.

## Read more

- [incident-start skill](../skills/incident-start/SKILL.md): `start.sh` modes, what each starts and its cleanup on exit
- [Operations runbook: Laptop to VM connectivity](../.docs/incident-profile-operations.md#3-laptop-to-vm-connectivity--ssh-troubleshooting)
- [Architecture: Native processes and containers](../.docs/architecture.md#native-processes-and-containers)
- [.dotfiles](../.dotfiles/README.md): optional shell setup for the VM
