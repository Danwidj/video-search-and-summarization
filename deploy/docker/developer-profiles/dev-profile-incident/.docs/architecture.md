# Incident Search and Reporting Profile: Architecture

The architecture of `dev-profile-incident`, the incident search and reporting profile built on NVIDIA's Video Search and Summarization (VSS) blueprint. The page follows the arc42 section order and the C4 model's levels (context, containers, components, deployment). It describes roles and interactions, not deployment values: ports, hosts, paths and settings live in the runbook, the skills and the agent contract page.

## Requirements

A reviewer uploads a surveillance or anomaly clip, and the system lets the reviewer:

- read a structured, timestamped incident report from a vision-language model (VLM): type, severity, confidence, a summary, and the entities, instruments and assets involved, each with the second it is seen;
- edit the report into new versions and mark one version per video official;
- search the whole archive in natural language over evidence items;
- ask questions about a report;
- read a dashboard that counts each video once.

The clip is kept in object storage and the report as an append-only revision. A standalone benchmark in `eval/` scores extraction against human ground truth; the console has no ground-truth screen.

Out of scope: user accounts, live streams, and more than one incident per video.

## Context and Scope

**Figure 1. System context diagram for the incident profile (C4 level 1).** One person, the Reviewer, uses the system in scope in a browser. The system stores rows in Supabase and media in Cloudflare R2, and sends prompts to hosted model endpoints. The Reviewer's browser plays video and loads images from R2 through video links, and the models fetch the video from R2 through a video link; neither read passes through the system.

![System context diagram: a Reviewer uses the incident search and reporting system in a browser; the system uses Supabase for rows, Cloudflare R2 for media and hosted model endpoints for inference; the Reviewer's browser and the models also read from R2 through video links](figures/figure-1-system-context.drawio.svg)

## Solution Strategy

Constraints first: the profile is allotted one GPU on a shared host, model inference is remote, and the agent has no authentication and holds the database service key.

1. **Reuse the stock VSS Agent and extend it in place.** The incident routes and tools are registered through the stock worker and tool registry. It runs natively for second-level restarts; stock media and perception appliances stay in containers.
2. **Infer remotely.** The one local GPU is left to the perception stack.
3. **One incident contract, two consumers.** The extraction prompt, JSON Schema, request settings, prompt registry and request goldens in `contracts/` are used by the console and vendored into the agent, with a strict validation policy and ID-only repair ([`analysis-schema.md`](analysis-schema.md)). A contract change bumps the version and updates both together.
4. **Reports are append-only revisions with an explicit official pointer.** An analysis appends an AI revision, an edit appends a human revision, a re-run starts a new AI branch, and failed attempts are run records only. "Latest run wins" is never inferred ([`data.md`](data.md#the-report-model)).
5. **Two analysis modes behind one console code path.** In agent mode the console calls the native agent, which extracts, locates, tracks and persists; in gateway mode the console calls the credential-holding gateway and persists itself.
6. **Object storage for media, the database for rows, local disks as caches.** Uploads go straight to object storage under readable keys that are never overwritten ([`data.md`](data.md#2-cloudflare-r2-storage-architecture)).
7. **Search is embed-then-retrieve over per-item evidence crops**, with pgvector in the database and a critic that is dormant by default.
8. **Tracking reuses the stock perception stack per clip** for people, and a seeded tracker corrected by the detector for instruments and assets; both are soft stages.
9. **The console is hexagonal.** Only adapters know tables, columns and function arguments; a test enforces the import boundaries.
10. **Long-running work is a database queue** with one in-process worker per console, so an analysis survives a closed tab.
11. **The stock search compose tag is reused** (`BP_PROFILE=bp_developer_search`), so the stack is a superset of the base and search pipelines.
12. **One video is one incident.** `videos.id` is the incident id, and every `report_revisions` row names its `video_id` ([`data.md`](data.md#the-report-model)).
13. **Reviewers are plain text.** `report_revisions.created_by` holds a name; there is no account table.

## Building Block View

### Level 1: Containers

**Figure 2. Container diagram for the incident profile (C4 level 2).** Containers are grouped by where they run: the laptop, the GPU workstation and the cloud services. The VSS Agent and the stock perception stack run on the GPU workstation; the console reaches the agent through an SSH tunnel. Arrow labels name the interaction in the arrow's direction. Colours mark stock VSS, built by the team and external services. The Final flow and the Midterm flow are marked on the arrows that belong to one of them only.

![Container diagram: on the laptop, incident-console-v2, vlm-gateway and mock-backend; on the GPU workstation, the VSS Agent, the perception stack containers and Phoenix; in the cloud, Cloudflare R2, Supabase and the hosted model endpoints; arrows show the Final flow and the Midterm flow](figures/figure-2-containers.drawio.svg)

| Container | Technology | Responsibility | Origin |
|---|---|---|---|
| `incident-console-v2` | Next.js App Router, React, TypeScript | The reviewer console and its server routes: upload with H.264 conversion, analysis orchestration, the background job worker, report versions, search, the dashboard and the chat panels; signs object-storage URLs; validates model output under the shared policy | Team-built |
| VSS Agent | NeMo Agent Toolkit (NAT) `nat serve` with the stock custom FastAPI worker | The stock agent plus the incident extension: analyse, evidence search, incident search, chat, evidence embeddings, charts and the reviewer box tools. Runs natively | Stock VSS, extended |
| Perception stack | Docker: NvStreamer, DeepStream perception (an RT-DETR detector with the NvDCF tracker), Kafka, Logstash, Elasticsearch, the video-analytics API | Turns an uploaded clip into per-frame person boxes with track ids. Used per clip by the agent's tracking stage | Stock VSS (search profile) |
| Phoenix | Docker | Trace viewer for NAT tool and workflow spans | Stock VSS infrastructure |
| `vlm-gateway` | FastAPI | Holds the remote inference credential server-side and forwards chat-completion requests unchanged. Used in gateway mode only | Team-built |
| `mock-backend` | FastAPI | A backup that mimics the backend: it stands in for the agent with deterministic embeddings and answers from a snapshot | Team-built |
| `contracts/` | JSON Schema, prompt files, JSON settings, fixtures, goldens | The incident contract, vendored into the agent by a sync script | Team-built |
| `supabase/` | SQL migrations, a SQL harness | The schema authority for the database, tested on a throwaway local Postgres | Team-built |
| Launcher and lifecycle scripts | Bash | One command from the laptop: preflight the host, heal missing services, start the native services and the tracking stack, open the tunnel, run the console | Team-built |
| Supabase Postgres | Managed Postgres, PostgREST, pgvector | Rows, database functions and row-level security that admits only the service role | External |
| Cloudflare R2 | S3-compatible object storage | Videos, thumbnails, evidence images and track files; private, read through signed URLs | External |
| Hosted model endpoints | OpenAI-compatible HTTPS APIs | A VLM for extraction, captions, grounding and zoomed looks; an LLM for chart requests and grounded chat; a text-embedding model | External |

Not started by the profile: Video IO & Storage (VIOS, also called VST), the HAProxy ingress, Redis, the stock web UI and the NIM containers.

### Level 2: The Console

`incident-console-v2` is one Next.js process: pages and API routes on top of feature modules, each split into domain (types and port interfaces), application (use cases) and infrastructure (adapters). A background job loop, started with the process, is a second driver of the analysis use case. `src/lib/container.ts` is the only file that picks adapters, and only `src/modules/*/infrastructure/supabase/` and `src/lib/postgrest/` name tables, columns and `p_*` arguments. Domain and application code import no infrastructure and no UI; sections import no infrastructure; `tests/import-boundaries.test.mjs` enforces both in `npm test`, and each exception is listed there with its reason. What each page does: [`console-reference.md`](console-reference.md).

**Figure 3. Component diagram for `incident-console-v2` (C4 level 3), by layer.** The client UI calls the pages and API routes, which call the use cases; the background job loop calls the same use cases. Use cases drive ports, the composition root picks the adapter behind each port, and the adapters reach Supabase, R2, the agent, the gateway and the contract files on disk. A few routes call adapters directly.

![Component diagram of incident-console-v2: client UI, pages and API routes, use cases, background job loop, ports, composition root and the adapters for Supabase, R2, the agent, the gateway, contract files and in-memory fakes](figures/figure-3-console-components.drawio.svg)

| Module | Responsibility |
|---|---|
| `analysis` | The one analysis path for uploads and re-runs: verify the stored object, sign a read URL, call the gateway or the agent, validate under the shared policy, record the attempt, store or verify the AI revision |
| `jobs` and the job loop | The background analysis queue: queue, claim, heartbeat, finish, retry and cancel |
| `reports` | Read one revision and its run into a report view; validate and save human edits; cut reviewer items on the server; mark or clear the official revision; store searchable crops; delete a video and its reports |
| `videos` | Run history |
| `search` | Evidence search and incident (revision) search through the agent |
| `chat` | The report and library chat through the agent |
| `dashboard` | The dashboard query, the chart specification allowlist, the chart interpreter and renderer |
| `contract` | A strict validator of the shared policy, and the catalogue that loads prompts, schema and allowlist from `contracts/` |
| `health` | Readiness as booleans only |

### Level 2: The Agent's Incident Extension

The extension is a set of routes registered by the stock worker ([`vm-api-contracts.md`](vm-api-contracts.md) lists them with their request and response shapes), NAT tools (`incident_report_gen`; the investigator's read tools `incident_read_report` and `incident_list_versions`; the editor's `propose_*` tools, which only propose draft changes), a vendored copy of the contract (`incident_contract/`), and utilities behind small interfaces: the remote VLM as the open-vocabulary detector and namer, object storage as the evidence and scratch store, and HTTP clients for the perception stack and the embedding endpoint.

The analysis pipeline, in order. "Soft" means a failure is recorded on the item or the run and the analysis continues.

| Stage | What it does | Soft | Code |
|---|---|---|---|
| Caption pass (flag) | Cuts a long clip into overlapping windows, captions each with the VLM and hands the captions to P1 as context | Yes | `utils/chunk_captions.py` |
| Set-of-marks (flag, needs tracking) | Draws a numbered box on each person track on a scratch copy of the clip, asks P1 for the number in each person's label, then strips the numbers | Yes | `utils/set_of_marks.py` |
| P1 extraction | Sends the signed video URL, the contract prompt and any reviewer prompt with the schema enforced through structured output; validates under `core-scored-v1` with `id-normalization-v1` | No: a violation is a client error and nothing is persisted | `tools/incident_report_gen.py`, `tools/incident_investigator.py`, `tools/incident_editor.py`, `tools/incident_experiments.py`, `incident_contract/` |
| RP1 prose report | A text report from the validated P1 JSON; the console asks for P1 only | Yes | `tools/incident_report_gen.py` |
| Person tracking (flag) | Runs beside the locate step: pushes the clip through the perception stack and builds person tracks from the frame pages | Yes | `utils/track_evidence.py`, `utils/perception_client.py` |
| Locate | Finds each entity, instrument and asset at its second with the detector, retrying the neighbouring seconds. An unfound item keeps a recorded gap | Yes | `utils/crop_evidence.py` |
| Gap retry | Looks again for an item left without a box: other seconds, the item's description as the label and a search in four overlapping tiles. A new box is kept only when the video model confirms it | Yes | `utils/crop_evidence.py` |
| Object tracking (flag) | Follows each located instrument and asset with a seeded single-object tracker forwards and backwards, re-anchored by the detector under its own budget and time cap | Yes | `utils/object_tracking.py` |
| Match and re-cut | Matches each located person to a track by box overlap and re-cuts the person's evidence at the track's first sample | Yes | `utils/track_evidence.py`, `utils/crop_evidence.py` |
| Zoomed second look and store | Two blind looks at each item (the marked frame, then a close-up) and a merge against the report's text, which may rename the item; then stores the frame, crop and track file | Yes | `utils/crop_evidence.py` |
| Revision | Appends the AI revision (payload, evidence, facet columns, no parent) with a summary embedding; retries on a revision-number clash | Best effort | `utils/incident_db.py`, `utils/embeddings.py` |
| Response and provenance | Returns the report, raw output, every P1 attempt, the tracking summaries and the per-stage provenance | | `utils/run_provenance.py` |

## Stock VSS and What the Team Added

The rule: team code lives in the profile directory or in files named `incident_*`; stock files are touched only to register or configure.

| Area | Stock VSS | Added by the team |
|---|---|---|
| Agent process (`services/agent`) | The NAT agents and tools, embeddings, the video-analytics MCP server. Modified only to register the incident routes and tools and to serve the dashboard chart routes | The `api/incident_*.py` route modules, `tools/incident_report_gen.py`, `incident_contract/` and the incident utilities under `utils/` |
| Perception and infrastructure | NvStreamer, DeepStream perception, Kafka, Logstash, Elasticsearch, the video-analytics API, Phoenix | The profile's Compose override (GPU pinning) and tracking Compose file, the tracking-stack script |
| Deployment packaging | The `dev-profile.sh` helper and the stock profiles, never used for this profile | `start.sh`, `.scripts/`, the profile's `compose.yml` |
| User interface | The stock web UI, not started | `incident-console-v2`, `vlm-gateway`, `mock-backend` |
| Storage and data | VIOS/VST and the stock object store, not started | `supabase/`, `contracts/`, the object-storage key layout |
| Operations and documentation | The stock `skills/` catalogue | The profile's `skills/`, `.docs/`, `AGENTS.md` and `README.md` |

## Runtime View

Contracts for the agent calls: [`vm-api-contracts.md`](vm-api-contracts.md); who writes which row: [`analysis-schema.md`](analysis-schema.md#6-agent-mode) and [`data.md`](data.md).

### Analysis Run in Agent Mode

**Figure 4. Analysis of an uploaded clip in agent mode (the vm mode default).** The sequence runs from the upload to the finished report. Person tracking runs beside the locate step, items left without a box get a gap retry, object tracking follows locate, each located person is matched to a track and re-cut, the zoomed second look runs before anything is stored (dropping crops called a different object), and each item's frame, crop and track are stored.

![Sequence diagram of an analysis in agent mode: upload and queue in the console, caption pass, report extraction by the hosted models, validation, locating and tracking evidence in parallel with the perception stack, storing evidence, saving the AI revision and finishing the job](figures/figure-4-analysis.drawio.svg)

1. **Upload** (console): a console route converts the file to an H.264 MP4 unless it already is one, puts it in object storage under a readable key that is never overwritten, and verifies the stored size.
2. **Queue** (console, database): the page queues a job with the chosen model; the console's job loop claims the oldest queued job and heartbeats while it runs.
3. **Prepare** (console): the analysis use case verifies the object, signs a read URL, creates the video row once, and calls the agent. The console owns the video row and the run row; the agent never writes the video row.
4. **Extract** (agent): optional captions, then P1 with the shared prompt and schema. A contract violation is answered as a client error with the raw output, and nothing is persisted.
5. **Evidence** (agent): the stages in the table above. Every stage is soft.
6. **Persist** (agent): the AI revision with its evidence and summary embedding.
7. **Record** (console): the console validates the raw output again, writes the immutable attempt record on its run row, verifies the agent's revision, stores the searchable crops when the video has no official revision yet, then finishes the job. A failed attempt leaves a run record, never a report.

### Analysis Run in Gateway Mode

Gateway mode (`ANALYSIS_MODE=gateway`) keeps the same console code path and swaps the model port: the console builds the identical P1 request, the gateway forwards it with the server-side credential, and the console persists the result itself. It is a backup that runs without the GPU host. No detector runs, so the evidence entries have no images and no searchable crops are stored.

**Figure 5. Analysis in gateway mode (the Midterm flow).** The sequence runs from the upload to the finished report: the same upload and queue steps as Figure 4, then the console verifies the object, reads the video length, creates the video row, sends the P1 request through `vlm-gateway`, validates the answer and saves the attempt record and the AI revision.

![Sequence diagram of an analysis in the Midterm flow: upload and queue in the console, then the console sends the report request through vlm-gateway to the hosted models, validates the answer and saves the attempt record and AI revision in Supabase, with no evidence images](figures/figure-5-analysis-midterm-flow.drawio.svg)

### Background Analysis Jobs

A queued upload is a row in `analysis_jobs` ([Data layer](data.md#analysis_jobs)). One loop per console process claims the oldest job through a database function that locks the row and skips locked ones, heartbeats while it runs, and recovers a job whose heartbeat stops. The loop runs one job at a time. Every console pointed at the same database shares the queue. The loop, the routes and the retry rules are in the [Console reference](console-reference.md#background-analysis-jobs).

### Evidence Search and Incident Search

**Figure 6. Natural-language evidence search.** The Reviewer's query is embedded by the agent and ranked in Supabase; the agent makes the crop and video links locally and records the query. The console then reads Supabase a second time for each hit's version and title. Crops load from R2 through their links, and the frame viewer cuts the frame on demand from the stored video.

![Sequence diagram of evidence search: the Reviewer types a query, the console calls the agent, the agent embeds the query and ranks crops in Supabase, makes links, optionally runs the critic and records the query, the console reads hit details from Supabase, and crops and frames load from R2](figures/figure-6-evidence-search.drawio.svg)

1. **What is searchable** (database): the evidence crops of each video's searchable revision, its official revision or else its newest ([`data.md`](data.md#evidence_crops)).
2. **Evidence search** (agent): one embed-then-retrieve function serves both the library-wide search and a search scoped to one incident. The critic is dormant by default, so a search costs one embedding call and one vector query.
3. **Incident search** (agent, console): the Find incidents text search retrieves the nearest revisions by their summary embedding, and falls back to a plain text match on the library when the agent fails or finds nothing.

### Reviewer Edit, the Official Version and Charts

1. **Save as new version** (console, database): the edit route validates the edit against the contract's sub-schemas and cross-field rules, cuts a reviewer-drawn item's crop, frame and track on the server, and calls one database function that appends a human revision and stores its crops in the same call. Earlier revisions are never changed.
2. **Mark official** (console, agent, database): the console fetches the revision's evidence embeddings from the agent and calls a database function that sets the video's official pointer and rebuilds that incident's searchable crops. An unreachable agent fails the mark and changes nothing.
3. **Re-generation** (console, agent): the same analysis path on the stored object; always a new run and a new AI branch that copies no earlier edit.
4. **Dashboard charts** (console, agent): for a chart request the agent's own LLM picks a chart specification; the console validates it against its allowlist, computes the figures from the database itself, and asks the agent to draw them. The model never sees a figure.
5. **Chat gap retry** (console, agent): the chat can ask the agent to look again for items of the saved report with no box; each found box becomes a proposal to confirm or adjust before Save.

**Figure 7. Retry missing boxes through chat.** The console starts a gap-retry job on the agent, which reads the saved report, reads the video and asks the hosted models to detect and check each item; the console polls the job and shows the boxes as proposals.

![Sequence diagram of a gap retry through chat: the Reviewer asks, the console starts a job on the agent, the agent reads the saved report from Supabase and the video from R2, detects and checks each item with the hosted models, the console polls and proposes boxes beside the items](figures/figure-7-gap-retry.drawio.svg)

## Deployment View

### Deployment Nodes

**Figure 8. Deployment diagram for the vm mode of the profile.** The laptop runs the console, and in mock mode the gateway and `mock-backend`; the GPU workstation runs the VSS Agent natively and the perception stack and Phoenix in Docker; the cloud services are reached over HTTPS. Mock mode runs the console, the gateway and the mock backend on the laptop alone, with the same cloud services.

![Deployment diagram: the laptop runs incident-console-v2, vlm-gateway and mock-backend; the GPU workstation runs the VSS Agent and, in Docker, the perception stack and Phoenix; Cloudflare R2, Supabase and the hosted model endpoints are cloud services; an SSH tunnel joins the console to the agent](figures/figure-8-deployment.drawio.svg)

### Native Processes and Containers

The policy is to run a service natively whenever that is feasible, and in a container when it is not:

- **Native:** the VSS Agent. A native process restarts in seconds after a code change, against a multi-minute image build, and the agent's virtual environment is installed editable from the checkout.
- **Containers:** the media and perception appliances (NvStreamer, DeepStream perception) depend on CUDA and GStreamer toolchains that are not installable on the host, and the infrastructure appliances (Kafka, Logstash, Elasticsearch, Phoenix) gain nothing from running natively. The stock Compose files use fixed container names, so one perception stack runs per host.
- **Not started:** the stock video storage and ingress services (VIOS/VST and HAProxy), Redis, the stock web UI and the NIM containers, because uploads go straight to object storage and inference is remote.

### Launch Modes and Connectivity

The launcher is the one daily entry point ([`incident-start`](../skills/incident-start/SKILL.md)); the procedures and troubleshooting are in the [runbook](incident-profile-operations.md#3-laptop-to-vm-connectivity--ssh-troubleshooting).

- **vm mode** (the default; agent mode): the launcher probes SSH to the host, starts only what is missing, starts the perception stack unless tracking is disabled, opens a backgrounded SSH tunnel that forwards only the agent's loopback endpoint, and starts the console in agent mode. Leaving the launcher stops only the laptop-side processes and the tunnel; the host keeps running.
- **mock mode** (a backup that mimics the backend, never a fallback when the host is unreachable): the launcher starts the mock backend and the gateway on the laptop; no SSH is used.
- **Connectivity:** the console talks to the agent through the tunnel, and to object storage and the database directly; the agent talks to the perception stack on its own host, and to object storage, the database and the model endpoints directly.

### Two Supabase Projects (One per Phase)

**Finals** is the live database: the console, the agent and the mocks all point at it. **Midterm** is the frozen record of the earlier phase: read-only, never pushed to, kept in the repository as an archive. The migration folder is the schema authority for finals ([`supabase/README.md`](../supabase/README.md)). Object storage is shared by both projects: the same keys, no copy. Which settings point each component at the live project are in the [`incident-manage-database`](../skills/incident-manage-database/SKILL.md) skill.

## Crosscutting Concepts

### Model Inference

All model calls are remote and OpenAI-compatible. The rules, and why they hold:

1. **Client type.** The agent's LLM and VLM clients are configured as OpenAI-type clients, never as NIM-type clients: the NIM LangChain client leaks client-only parameters (such as the SSL-verification flag) into the HTTP request body, which standard OpenAI-compatible endpoints reject with a bad-request error.
2. **Base URLs carry no version path.** The agent and the LangChain clients append the API version segment themselves, so a configured base URL that already ends with it produces a wrong path.
3. **One credential, many roles.** One server-side key serves the agent's LLM and VLM; the gateway holds its own copy of the hosted key for the console's gateway mode, so the browser never sees it.
4. **Capabilities the models must have.** The LLM must support tool calling and schema-constrained output; the VLM must accept a video by URL with schema-constrained output, and images for the grounding, zoom and box-description calls. The allowlisted VLMs, their request settings and per-model timeouts are in the contract settings.
5. **Sparse frames.** Hosted video models sample a bounded number of frames per request, so a long clip is seen sparsely; the caption pass exists to recover short actions.
6. **Embeddings** come from one text-embedding model, used for evidence passages, revision summaries and queries alike, so cosine distance is meaningful.

### Secrets and Access Control

Credentials live only in server processes: the console's server routes, the gateway and the agent. The console's health route answers booleans. The database admits only the service role ([`data.md`](data.md#row-level-security-rls--access-control)). Object storage is private and read through expiring signed URLs. The agent binds its host's loopback and is reached only through the SSH tunnel.

### Resilience and Recorded Failure

Nothing optional fails an analysis: a caption, locate, zoom, tracking or embedding failure is recorded on the item or the run and the pipeline continues. A contract or request failure is an attempt record on the run with the raw output, never a report, and the job fails with a plain reason that the page shows with a retry. A lost console is detected by a missing heartbeat and its job re-queued once.

## Risks

- **The analysis queue is shared** by every console pointed at the same database, so a job may run on another person's console and code version.
- **The agent has no authentication;** its safety rests on the loopback bind and the tunnel, and on the host staying inside a trusted network.
- **One GPU on a shared host** bounds throughput, and the perception stack holds GPU memory while it is up.
- **Hosted endpoints are outside the team's control:** rate limits, sparse frame sampling and endpoint changes reach the product directly.

## Glossary

| Term | Meaning here |
|---|---|
| Analysis mode | How the console gets a report: **agent** mode calls the VSS Agent, which also locates, tracks and persists; **gateway** mode calls `vlm-gateway` and the console persists |
| Final flow, Midterm flow | Labels on Figures 2 and 5 for the two analysis paths: the Final flow is agent mode (launched as vm mode), the Midterm flow is gateway mode (launched as mock mode). Prose uses the setting names |
| Evidence item, evidence entry | An entity, instrument or asset of a report; its entry holds the crop, the frame, the box, the track and any gap reasons |
| Locate step, grounding | The detector call that finds an item's bounding box in the frame at its second |
| NAT, NIM | NVIDIA's NeMo Agent Toolkit, the framework the VSS Agent runs on; NVIDIA Inference Microservice, a model-serving container (none runs in this profile) |
| Official revision, searchable revision | The revision a reviewer marked as the video's report; the official revision, or else the newest, is the one search indexes |
| P1, RP1 | The extraction call that returns the structured report, and the prose-report call that follows it (skipped by the console) |
| Perception stack | The stock VSS search-profile containers that turn a clip into per-frame person boxes with track ids |
| Set-of-marks | Numbered person boxes drawn on the clip P1 sees, so P1 can name which track each person is |
| Zoomed second look | Two blind VLM looks at a located item and a merge that may rename it with a recorded confidence |
