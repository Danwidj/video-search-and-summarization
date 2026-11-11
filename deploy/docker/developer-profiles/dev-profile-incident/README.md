<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
<!--
agents:
  read-when: Deploying or starting the incident profile; adding, moving or renaming a doc or skill.
  owns: the deployment steps (prerequisites, copy and fill in .env, symlinks, database setup, start, check, stop) and the documentation index.
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

The committed [`.env`](.env) is the template for both machines. Section 1 lists every setting you fill in, blank; section 2 holds the defaults. Copy it, then fill in section 1 of the copy. Never put a real value in `.env` itself, never commit a copy, and never print the values.

**Laptop**, in this folder:

```bash
cp .env .env.local
```

Each sub-service reads its own `.env.local`. Link the shared file into the three of them, from this folder:

```bash
ln -sfn ../.env.local incident-console-v2/.env.local
ln -sfn ../.env.local vlm-gateway/.env.local
ln -sfn ../.env.local mock-backend/.env.local
```

Running `.githooks/activate.sh` once per clone keeps these links (and the copy, in new worktrees) in place ([.githooks](../../../../.githooks/README.md)). The hook leaves a VM checkout alone: where the folder has a `.env.remote` and no `.env.local`, it creates neither `.env.local` nor the links.

**VM**, in this folder of the VM's checkout (default `/srv/rise-up/vss`, changed with `VSS_REPO_ROOT`):

```bash
cp .env .env.remote
```

The VM is not expected to have a `.env.local`. The scripts stop with this command if the file is missing; there is no fallback to `.env`. The older name `generated.env.remote` is still accepted when it is the only one; if both exist, `.env.remote` wins and the script says so.

| Section 1 setting | Where | Meaning |
|---|---|---|
| `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY`, `INCIDENT_DB_DSN` | both | The Supabase project |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET` | both | The Cloudflare R2 bucket |
| `VSS_SSH_HOST` | laptop only | SSH host name or address of the VM. No default. `VSS_SSH_USER` or `VSS_SSH_TARGET` are optional extras ([start.sh](start.sh) header) |
| `NGC_CLI_API_KEY`, `OPENAI_API_KEY` | VM only | Keys for container images and the model endpoint |
| `LLM_BASE_URL`, `LLM_NAME`, `VLM_NAME` | VM only | Model endpoint (no `/v1`) and model names |

Section 2 holds defaults. Three of them are blank on purpose and the VM scripts fill them in for each run (a value you type wins, and the file is left alone except `HOST_IP`):

- `HOST_IP`: the VM's address. `vm-ensure-docker.sh` writes it into `.env.remote` (after a backup) when it is blank, missing or stale. `native-services.sh`, `rebuild-svc.sh` and `tracking-stack.sh` use it for the run without changing the file. Each stops if it cannot find the address.
- `VSS_APPS_DIR`: the checkout's `deploy/docker`.
- `VSS_DATA_DIR`: `<checkout>/.data` (git-ignored, shared by everyone using the checkout).

The eval settings (`EVAL_LLM_JUDGE_NAME`, `EVAL_LLM_JUDGE_BASE_URL`, `EVAL_DIR`, `DATASET_FILE_NAME`) and `RTVI_VLM_BASE_URL` have working defaults, because the agent config reads them and refuses to start when one is unset. `test-env-template.sh` fails when the config gains a setting the template leaves unset.

Optional blanks: `VLM_MODEL` (the console falls back to its built-in model), and `VLM_GATEWAY_BASE_URL` with `VLM_GATEWAY_API_KEY`. The laptop needs the gateway pair only for mock mode and `eval/`; the VM never needs it (its Compose no longer includes the gateway, and the agent reads the pair only as an override of `VLM_BASE_URL` and `OPENAI_API_KEY`).

Leave `VSS_AGENT_HOST` on loopback. More rules for the VM file: [operations runbook](.docs/incident-profile-operations.md).

**Database (new, empty Supabase project only):** once `INCIDENT_DB_DSN` is filled in `.env.local`, run `./.scripts/setup-database.sh --env-file .env.local` on the laptop. It creates every table and function from [supabase/migrations](supabase/migrations/) and stops if the database already has the schema ([details](supabase/README.md#build-a-new-database)).

## 3. Start

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

The diagrams call the two flows the Midterm flow (run with `--mode mock`) and the Final flow (run with `--mode vm`); the flags keep their names.

What vm mode starts, in order:

1. **On the VM, over SSH:** checks what is running and starts only what is missing. It clones the checkout if there is none, pulls missing images, and starts Phoenix (trace viewer) in Docker and the agent (`vss-agent`, port 8000) as a native process.
2. **On the VM:** the person-tracking stack in Docker. `ENABLE_TRACKING=false ./start.sh` skips it. Its first start takes about ten minutes.
3. **On the laptop:** an SSH tunnel from `localhost:8000` to the agent.
4. **On the laptop:** the console at <http://localhost:3200>.

Mock mode starts the mock backend (`127.0.0.1:7777`), the model gateway (`127.0.0.1:8600`) and the console, all on the laptop.

## 4. Check it is up

| Check | Expect |
|---|---|
| `curl -s localhost:3200/api/health` | The console answers with true/false readiness flags |
| `./.scripts/tunnel-check.sh` | `agent ok` and `search route ok` (vm mode) |
| `curl -s 127.0.0.1:7777/health` | The mock backend answers (mock mode) |

If `start.sh` stops early, it prints the cause and the fix. More help: [incident-start skill](skills/incident-start/SKILL.md) and [connectivity troubleshooting](.docs/incident-profile-operations.md#3-laptop-to-vm-connectivity--ssh-troubleshooting).

## 5. Stop

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
| [vlm-gateway](vlm-gateway/README.md) | Key-holding proxy for the Midterm flow |
| [mock-backend](mock-backend/README.md) | Two zero-GPU mocks that mimic the backend |
| [contracts](contracts/README.md) | The incident contract: prompt, schema, goldens |
| [supabase](supabase/README.md) | Database schema (migrations) and SQL harness |
| [eval](eval/README.md) | The P1/RP1 benchmark |
| [skills](skills/README.md) | Agent skills for operating the profile |
| [.scripts](.scripts/README.md) | Lifecycle scripts |
| [archived](archived/README.md) | The frozen midterm database record, copy and R2 scripts, read-only |

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
