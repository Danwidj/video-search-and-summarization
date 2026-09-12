# VM parity report (Phase 2): live base deploy vs `base_profile_mock` baseline

Comparison baseline: `LOCAL_MOCK_LOOP.md` (branch `fm/vss-incident-phase1-mock`) —
25 mock routes verified locally with `uv`, no GPU. All live probing below ran
over SSH on `kwanz-ws` (`/srv/rise-up/vss`) through the deployed HAProxy on
`http://localhost:7777`, unless noted. No secret value was read, printed, or
committed at any point (presence checks used `test -f`/`stat` size only; logs
were passed through a credential-masking filter before reading).

## 1. Deploy performed

Per decision, the stock **base** profile (local LLM/VLM) — `dev-profile.sh`
accepts only `base/lvs/search/alerts`, not `incident`:

```bash
cd /srv/rise-up/vss
set -a; source /srv/rise-up/.ngc_env; set +a
./deploy/docker/scripts/dev-profile.sh up --profile base --hardware-profile OTHER \
  --host-ip 10.131.1.5 --external-ip localhost \
  --llm nvidia/nvidia-nemotron-nano-9b-v2 --llm-device-id 0 \
  --vlm nvidia/cosmos3-reasoner --vlm-device-id 1
```

Result: CPU services healthy (`vss-agent`, `vss-vios-ingress`,
`vss-vios-postgres`, `vss-haproxy-ingress`, `vss-agent-ui`, redis, phoenix).
**All GPU containers failed to start** — host driver fault (see §5):
`nvidia-smi` on the host itself reports
`Failed to initialize NVML: Driver/library version mismatch (NVML 595.91)`.
NIMs (`nemotron-nano-9b-v2`, `cosmos3-reasoner`), `streamprocessing`, and
`sensor` sit in `Created`. Images for both NIMs are cached, so no pull is
needed once the driver is fixed.

Operational notes:
- The script's `up` flow runs `docker compose -p mdx down -v` first ("with
  volumes"): it recreated the `mdx_*_cache` NIM volumes, so first NIM start
  re-downloads weights even though images are cached.
- It needed no `sudo` (prompts failed, deploy continued regardless).

## 2. VM tree conflict (held item, resolved per instruction)

`services/agent/src/vss_agents/tools/video_report_gen.py` had 3 conflict
hunks (`Updated upstream` vs `Stashed changes`, stash@{0}
`vm-run-pre-sync-1789194373` vs origin/main PR #15 `09d02c4c9`):
1. `max_images_per_vlm_call` Field: upstream adds `gt=0`; stash drops the line.
2. VLM-config resolution: upstream fail-soft (`vu_config=None`, warn on
   failure); stash additionally resolves the VLM model name for an audio-suffix
   guard with an info log.
3. Chunk-size enforcement: upstream fail-closed (`ValueError` when
   `max_fps` unresolvable, 85%-of-cap safety budget); stash silent-skips when
   `vu_max_fps` is falsy (`if config.max_images_per_vlm_call and vu_max_fps`).

Per instruction the working-tree file was overwritten byte-identical with
`origin/main` (`diff` clean, 105514 bytes) and nothing else touched.
`git status` still shows the path as `UU` (index stages unresolved) — left
exactly so for the captain's call; no `add`/`commit`/`stash` was run.
Follow-on finding: the conflict is **inert for the running stack** —
`vss-agent` is image-only in compose (no `build:` section; `docker compose
build vss-agent` is a no-op, image `66662f...` unchanged) and only
`deploy/docker` is bind-mounted into the container, not `services/agent`.
The agent started with zero errors and reports healthy.

## 3. Route table parity (HAProxy vs mock prefixes)

Real `haproxy.cfg` routes: `/api/*` → agent, `/chat*` → agent,
`/websocket*` → agent, `/static*` → agent, `/vst/*` → vst-ingress,
everything else (incl. `/generate*`, `/health`) → UI container. The mock
serves all of these prefixes on one port, so prefix-level parity holds
except `/generate*` and `/health` (see gaps P3, P1).

## 4. Endpoint side-by-side (mock → live)

| Mock route | Mock shape | Live shape | Verdict |
|---|---|---|---|
| `GET /health` | 200 `{"value":{"isAlive":true}}` | 404 Next.js page (falls through to UI) | **P1 GAP** — status + body |
| `POST /api/v1/videos` `{"filename"}` | 200 `{"url":"…/vst/api/v1/storage/file"}` | 200 **identical** `{"url":"http://localhost:7777/vst/api/v1/storage/file"}` | **PARITY** |
| `POST /api/v1/videos/{sid}/complete` | 200 `{message,sensor_id,filename,chunks_processed}` | 502 `{"detail":"Timelines API failed: … VST … 502"}` | Env-degraded (VST upstreams GPU-dead); error shape matches the real `video_ingest.py` contract |
| `DELETE /api/v1/videos/{id}` | 200 `{status:"success"\|"partial",message,video_id}` | 200 `{status:"failure",message:"Failed to delete video 'VID1'",video_id}` | **P2 GAP** — same keys, real uses `"failure"` for missing video where mock says `"partial"` |
| `POST /api/v1/rtsp-streams/add` | 200 `{status:"success",message,error:null}` | 200 `{status:"failure",message:"Failed at VST: …502…",error:"VST error: …"}` | Keys match; healthy-path behavior unverifiable while VST is down |
| `DELETE /api/v1/rtsp-streams/delete/{n}` | 200 `{status,message,name}` JSON | 500 `Internal Server Error` (text) | **P4 GAP** — status + content type (VST 502 propagates uncaught) |
| `POST /chat` | 200 OpenAI envelope `{id,object,created,choices}` | 200 envelope **plus** `model:"unknown-model"`, `usage:{…}`, `service_tier` | Minor gap — extra real fields; error content inline when LLM down |
| `GET /chat` | 200 (mock allows GET) | 405 `{"detail":"Method Not Allowed"}` | **P5 GAP** — mock over-accepts GET |
| `POST /chat/stream` | SSE `data:` OpenAI chunks + `data: [DONE]` | SSE interleaves `intermediate_data: {…markdown…}` lines with `data:` chunks; workflow runs for real, fails only at LLM connect (`10.131.1.5:30081` refused) | **P6 GAP** — envelope differs; no `[DONE]` observed |
| `POST /generate`, `/generate/stream` | 200, same as chat | 404 Next.js (haproxy sends to UI, no agent route) | **P3 GAP** — route-level; UI only ever calls `/chat/stream`, so likely dead surface |
| `GET /static/{f}` | 404 `"not found"` | 404 `{"detail":"No object found with key: …"}` | Minor gap — 404 body text |
| `WS /websocket` | full HITL round-trip | 101 Switching Protocols accepted | Prefix parity; full HITL round-trip not exercised live (needs scripted client; LLM dead regardless) |
| 13× `/vst/api/v1/*` (storage/sensor/replay) | canned 200s / `[]` / placeholder JPEG | all 502 from ingress nginx (upstreams GPU-dead) | Prefix parity at HAProxy (`/vst/*` → ingress, ingress responds); per-endpoint shapes **UNVERIFIED — waits on GPU fix** |

## 5. Incident-console paths (credentials half — resumed after secrets arrived)

Secrets file: present **only** at
`deploy/.../dev-profile-incident/incident-console/.env` (534 bytes, VM only,
absent from the local worktree); git-ignored (root `.gitignore:22`) and
untracked — never staged or committed. Compose uses shell environment only
(no `env_file`), so the console was (re)created with the secrets sourced in
the deploy shell; values never printed.

- Container `vss-incident-console` (Streamlit :8501) up; `/`, `/1_Catalog`,
  `/2_Report_Review`, `/3_Dashboard`, `/4_Severity_Eval`, `/_stcore/health`
  all HTTP 200 — same page set as the local loop.
- Postgres: `scripts/seed_supabase.py` (idempotent upsert per its docstring)
  run against the real DSN **hung without output** (~8 min, killed as
  tidy-up; re-runnable idempotently). A separate 55 s read-only count query
  also returned nothing. Verdict: connections hang rather than fail fast —
  whether the DSN host is unreachable from the VM or the DB is stalled is
  not diagnosable without reading the value, which is prohibited. **WAITS
  ON: DSN reachability check by whoever holds the value** (or a
  redacted host:port for a TCP test). No rows were confirmed written.
- R2: `configured()` → True; `list_video_keys()` → **1918 keys**
  (`anomaly/…`); `playback_url()` returns a signed `r2.cloudflarestorage.com`
  URL with expiry params. Catalog + playback-URL path verified live.
- Agent upload client: covered by §4 (`POST /api/v1/videos` parity).
- AI-trigger endpoints (`POST /api/v1/incidents/{id}/analyze`,
  `POST /api/v1/search`): **do not exist anywhere yet** (shared plan §4,
  design-only, no implementation) — gap by definition, not a regression.

## 6. Waiting list (needs captain/firstmate)

1. **Host GPU driver mismatch** (`nvidia-smi` fails, NVML 595.91) — needs
   host intervention (driver reinstall/reboot of a shared box, 24 users);
   blocks: NIM start, real chat/VLM answers, all 13 VST endpoint shapes,
   healthy-path video complete/RTSP behavior.
2. **Merge index** still `UU` on `video_report_gen.py` (working file now
   == origin/main) — captain's call to resolve.
3. **Postgres TBD** (§5 Postgres hang) — confirm from a re-run once
   reachability is established.
4. Out of scope, noted only: git hooks, SSH tunnel aliases, R2/direnv
   integration (separate phases).
