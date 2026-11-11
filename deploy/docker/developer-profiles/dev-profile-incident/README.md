<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
<!--
agents:
  read-when: Deploying or starting the incident profile; adding, moving or renaming a doc or skill.
  owns: the deployment steps (prerequisites, settings, symlinks, start, check, stop) and the documentation index.
  rules: Update the index below in the same change as any doc or skill you add, move or rename. Setting names only, never values.
-->

# Incident profile: deployment

<!-- TODO(video): demo video goes here -->

How to deploy and run the incident search and reporting system. The backend runs on a GPU VM (the workstation); the web console runs on your laptop and reaches the backend through an SSH tunnel. Coding agents start at [AGENTS.md](AGENTS.md).

## 1. What you need

- **A GPU VM** you can reach over SSH without a password prompt (key login), with Docker and the NVIDIA container runtime. The project uses GPU 0 only.
- **On your laptop:** `ssh`, Node.js with `npm`, and `uv`. If the VM is on a Tailscale network, Tailscale must be connected.
- **Accounts and keys:** a Supabase project (database), a Cloudflare R2 bucket (videos and evidence images), an OpenAI-compatible endpoint and key for the language and vision models, and an NVIDIA API key (embeddings and container images).

## 2. Settings

Two untracked files hold the settings. Never commit either, and never print their values.

### On your laptop: `.env.local`

Put it in this folder.

| Setting | Meaning | Example |
|---|---|---|
| `VSS_SSH_HOST` | SSH host name or address of the VM. Required for vm mode; there is no built-in default | `my-gpu-vm` |
| `VSS_SSH_USER` | Your login on the VM. Optional: falls back to `User` in `~/.ssh/config`, then your local user name | `alice` |
| `INCIDENT_SUPABASE_URL` | URL of the Supabase project | `https://<project>.example` |
| `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | Service role key of that project | `<service-role-key>` |
| `R2_ACCOUNT_ID` | Cloudflare account that owns the bucket | `<account-id>` |
| `R2_ACCESS_KEY` | R2 access key | `<access-key>` |
| `R2_SECRET_KEY` | R2 secret key | `<secret-key>` |
| `R2_BUCKET` | Bucket for videos and evidence images | `<bucket-name>` |
| `VLM_GATEWAY_BASE_URL` | Model endpoint for the local gateway. Mock mode only | `https://<model-endpoint>` |
| `VLM_GATEWAY_API_KEY` | Key for that endpoint. Mock mode only | `<api-key>` |

`VSS_SSH_TARGET` (a full `user@host`) may replace `VSS_SSH_HOST` and `VSS_SSH_USER`. Other optional overrides are listed in the header of [start.sh](start.sh).

### On the VM: `generated.env.remote`

Put it in this folder of the VM's checkout (default checkout: `/srv/rise-up/vss`, changed with `VSS_REPO_ROOT`). `start.sh` cannot create it, and stops if it is missing.

| Setting | Meaning | Example |
|---|---|---|
| `VSS_APPS_DIR` | Absolute path of `deploy/docker` in the VM checkout | `/srv/rise-up/vss/deploy/docker` |
| `VSS_DATA_DIR` | Folder for persistent service data | `/srv/rise-up/vss-apps-data` |
| `HOST_IP` | The VM's own network address. `start.sh` corrects a stale value | `<vm-ip>` |
| `EXTERNAL_IP` | Address used in links sent to the browser | `localhost` |
| `VSS_AGENT_CONFIG_FILE` | Agent configuration; must be the base profile's file | `./deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml` |
| `REPORT_REFERENCE_BASE_DIR` | Any existing folder; the agent configuration requires it | `/tmp` |
| `LLM_NAME`, `VLM_NAME` | Language model and vision-language model names | `<model-name>` |
| `LLM_BASE_URL`, `VLM_BASE_URL` | Model endpoints, without a trailing `/v1` | `https://<model-endpoint>` |
| `LLM_MODEL_TYPE`, `VLM_MODEL_TYPE` | Client type; always `openai` | `openai` |
| `OPENAI_API_KEY` | Key for the model endpoints | `<api-key>` |
| `NVIDIA_API_KEY` | Key for the embedding endpoint | `<api-key>` |
| `NGC_CLI_API_KEY` | Key for pulling NVIDIA container images | `<api-key>` |
| `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | The same Supabase project as on the laptop | as above |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET` | The same R2 bucket as on the laptop | as above |

Leave `VSS_AGENT_HOST` unset, so the agent listens on the VM's loopback only. More rules for this file: [operations runbook](.docs/incident-profile-operations.md).

## 3. Symlinks

Each sub-service reads its own `.env.local`. Link the shared file into them, from this folder:

```bash
ln -sfn ../.env.local incident-console-v2/.env.local
ln -sfn ../.env.local vlm-gateway/.env.local
ln -sfn ../.env.local mock-backend/.env.local
```

Running `.githooks/activate.sh` once per clone keeps these links in place across worktrees ([.githooks](../../../../.githooks/README.md)).

## 4. Start

Run from this folder, on your laptop (never on the VM):

```bash
./start.sh --mode vm
```

| Command | What it does |
|---|---|
| `./start.sh --mode vm` | The default. Real backend on the VM, console on the laptop |
| `./start.sh --mode vm --prod` | The same, with the console as a production build (`next build`, then `next start`) |
| `./start.sh --mode vm --no-console` | Backend and tunnel only |
| `./start.sh --mode mock` | No VM and no GPU: a local mock that mimics the backend. A backup only; verify real work in vm mode |

What vm mode starts, in order:

1. **On the VM, over SSH:** checks what is running and starts only what is missing. It clones the checkout if there is none, pulls missing images, and starts Phoenix (trace viewer) in Docker and the agent (`vss-agent`, port 8000) as a native process.
2. **On the VM:** the person-tracking stack in Docker. `ENABLE_TRACKING=false ./start.sh` skips it. Its first start takes about ten minutes.
3. **On the laptop:** an SSH tunnel from `localhost:8000` to the agent.
4. **On the laptop:** the console at <http://localhost:3200>.

Mock mode starts the mock backend (`127.0.0.1:7777`), the model gateway (`127.0.0.1:8600`) and the console, all on the laptop.

## 5. Check it is up

| Check | Expect |
|---|---|
| `curl -s localhost:3200/api/health` | The console answers with true/false readiness flags |
| `./.scripts/tunnel-check.sh` | `agent ok` and `search route ok` (vm mode) |
| `curl -s 127.0.0.1:7777/health` | The mock backend answers (mock mode) |

If `start.sh` stops early, it prints the cause and the fix. More help: [incident-start skill](skills/incident-start/SKILL.md) and [connectivity troubleshooting](.docs/incident-profile-operations.md#3-laptop-to-vm-connectivity--ssh-troubleshooting).

## 6. Stop

- **Laptop:** Ctrl-C in the `start.sh` terminal stops the console, the tunnel and any local mock services.
- **VM:** nothing on the VM stops when `start.sh` exits, because the backend is shared. To stop it on purpose, run on the VM, from this folder:

  ```bash
  ./.scripts/native-services.sh stop   # the agent
  ./.scripts/tracking-stack.sh stop    # the person-tracking stack
  ./.scripts/down.sh                   # the agent and all containers, nothing removed
  ```

Never use NVIDIA's `dev-profile.sh` for this profile: its `down` deletes the VM's data and model cache.

## What is inside

| Folder | What it is |
|---|---|
| [incident-console-v2](incident-console-v2/README.md) | The Next.js console |
| [vlm-gateway](vlm-gateway/README.md) | Key-holding proxy for the mock flow |
| [mock-backend](mock-backend/README.md) | Two zero-GPU mocks that mimic the backend |
| [contracts](contracts/README.md) | The incident contract: prompt, schema, goldens |
| [supabase](supabase/README.md) | Database schema and SQL harness; the [midterm record](supabase/midterm/README.md) is frozen |
| [eval](eval/README.md) | The P1/RP1 benchmark |
| [skills](skills/README.md) | Agent skills for operating the profile |
| [.scripts](.scripts/README.md), [.dotfiles](.dotfiles/README.md) | Lifecycle scripts; optional VM shell setup |
| [archived](archived/README.md) | Retired code, read-only |

## Read more

- [Status](.docs/status.md): what runs today, known issues, open actions
- [Action plan](.docs/action-plan.md): goals and scope
- [Architecture](.docs/architecture.md): context, containers, runtime and deployment
- [Console reference](.docs/console-reference.md): pages, routes and configuration
- [Data layer](.docs/data.md): tables, functions, security, R2 keys
- [Analysis schema](.docs/analysis-schema.md): report fields, prompts, validation
- [Operations runbook](.docs/incident-profile-operations.md): running the VM
- [VM API contracts](.docs/vm-api-contracts.md): agent endpoints and the tunnel
- [Decision log](.docs/decisions.md): why things are the way they are; [superseded entries](.docs/archive/decisions-superseded.md) are archived
- [Search spec](.docs/mvp2/README.md), [console layout](.docs/mvp2/console-hexagonal-architecture.md), [report-first chat routing](.docs/mvp2/chat-routing.md), [search evaluation](.docs/mvp2/eval.md), [experiment decisions](.docs/mvp2/experiment-decision-record.md)
- Evaluation reports: [final report](eval/docs/experiments/final-report.md), [methodology v2.0](eval/methodology/evaluation-methodology-v2.0.md), [all experiment reports](eval/docs/experiments/)
