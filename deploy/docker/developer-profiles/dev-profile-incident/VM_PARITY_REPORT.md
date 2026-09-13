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
   **RESOLVED 2026-09-13 (see §7):** captain rebooted kwanz-ws; both
   A6000s healthy, full stack up, all held checks re-run.
2. **Merge index** still `UU` on `video_report_gen.py` (working file now
   == origin/main) — captain's call to resolve.
   **RESOLVED 2026-09-13:** VM tree now clean at `8c20470`, no conflict
   markers; nothing to resolve.
3. **Postgres TBD** (§5 Postgres hang) — confirm from a re-run once
   reachability is established.
   **UPDATED 2026-09-13 (see §7):** retested; fails at the Postgres
   handshake layer on the VM only (laptop works). Needs network owner.
4. Out of scope, noted only: git hooks, SSH tunnel aliases, R2/direnv
   integration (separate phases).

## 7. Phase-2b retest after captain reboot (2026-09-13 ~01:29-01:45 UTC)

Preconditions cleared: `nvidia-smi` reports both RTX A6000s healthy
(driver 595.91.07, ~39/37 GiB used by the two NIMs, 0% util at check
time). Full stack up and healthy: `vss-agent`, `vss-vios-ingress`,
`vss-vios-streamprocessing`, `vss-vios-sensor`, both NIMs
(`nemotron-nano-9b-v2` :30081, `cosmos3-reasoner` :30082),
`vss-incident-console`, `vss-vios-postgres`, `vss-haproxy-ingress`,
phoenix, redis. VM tree clean at `8c20470`. All probes below went
through HAProxy `http://localhost:7777` over SSH. One 11 MB probe video
was uploaded, completed, verified, and deleted — VST left empty
(`timelines` → `null`, `sensor/streams` → `[]`).

### 7a. Chat / stream now live (P6 narrowed)

- `POST /chat` returns a real LLM answer (`"OK"`) in the OpenAI
envelope plus `model:"unknown-model"`, `usage`, `service_tier` —
minor extra-fields gap only, as recorded in §4.
- `POST /chat/stream` runs the real workflow and terminates with
`data: [DONE]` after `data:` chunks — the §4 "no `[DONE]` observed"
was purely LLM-down behavior. Remaining P6 delta is narrower: the
live stream interleaves `intermediate_data: {markdown workflow-trace}`
lines the mock never emits.
- `POST /api/v1/videos/{sid}/complete` with **no body** → 422
`{"detail":[{"type":"missing","loc":["body"]…}]}`. The mock
declares the body required too (`body: VideoUploadCompleteInput`, no
default), so this is **parity**, not a gap.

### 7b. Healthy-path video ingest verified end to end

Mirrored the real UI client (`chunkedUpload.ts`: multipart POST with
`mediaFile`/`filename`/`metadata` fields plus `nvstreamer-*` headers,
single chunk) against the 11 MB sample clip as `parity-probe.mp4`:

- Upload → 200
`{bytes, chunkCount, chunkIdentifier, created_at, filePath,
filename:"parity-probe" (extension stripped), id, sensorId, streamId}`.
Mock returns `{id, filename (extension kept), bytes, streamId,
sensorId, filePath, timestamp, created_at}` — **gap**: mock lacks
`chunkCount`/`chunkIdentifier`, keeps the extension, and adds
`timestamp`.
- `POST /api/v1/videos/{sid}/complete` `{"filename":…}` → 200
`{message:"Video parity-probe.mp4 successfully uploaded to VST",
sensor_id, filename, chunks_processed:0}` — **parity** on keys with the
mock `VideoIngestResponse` (mock fills `chunks_processed` from its own
tracking; live returns 0).
- `GET /vst/api/v1/storage/timelines` → 200
`{sid:[{startTime:"2025-01-01T00:00:00.000Z",
endTime:"2025-01-01T00:01:21.567Z"}]}` — populated shape matches the
mock's `{sid:[{startTime,endTime}]}`. **Parity when non-empty.**
- `DELETE /api/v1/videos/{sid}` (existing) → 200 `{status:"partial",
message:"…partially deleted - some steps failed…", video_id}`.
Refines P2: the mock uses `"success"` for existing / `"partial"`
for missing (2-way), while live uses `"partial"` for existing-with-
failures and `"failure"` for missing (3-way: success/partial/failure).
Same keys, different status vocabulary.
- `videoUrl` from the file-url endpoint points at
`http://10.131.1.5:30888/…` (VST internal host:port, not HAProxy) —
playback from outside the VM needs the tunnel aliases phase (noted,
out of scope).
- Robustness note (code reading + live `null`): the agent's
`get_timeline` does `timelines_data.get(stream_id, [])` on
`GET /storage/timelines`, but empty VST returns `null`, so on a fresh
box the lookup raises `AttributeError` (not `VSTError`) before the
"No timeline" path. Flagged, not fixed (parity task, no code change).

### 7c. VST per-endpoint shapes, live (was: all 502)

| Live endpoint | Live shape (200 unless noted) | Mock shape | Verdict |
|---|---|---|---|
| `GET /sensor/version` | `{"type":"vst","version":"2.1.0-26.05.4"}` | same keys, `"1.0.0-mock"` | **PARITY** (version differs, expected) |
| `GET /sensor/streams`, `GET /replay/streams` | `[]` | `[]` empty-state | **PARITY** |
| `GET /storage/timelines` (empty) | `null` | `{}` | **GAP P7** — null vs empty object |
| `GET /storage/size` | `{total:{remainingStorageDays, sizeInMegabytes, totalAvailableStorageSize, totalDiskCapacity}}` | `{totalBytes, totalSize[, timelines]}` | **GAP P8** — wholly different keys |
| `GET /storage/{id}/timelines` | bare array `[{startTime,endTime}]` | `{id:[…]}` object wrapper | **GAP P9** — mock over-wraps |
| `GET /storage/file/{id}/url` (no params) | 400 `{error_code:"InvalidParameterError", error_message:"Start and end time are required"}` | 200 `{videoUrl}` unconditional | **GAP P10** — real requires `startTime`/`endTime` (+`container`) |
| `GET /storage/file/{id}/url` (with time params) | 200 `{videoUrl, absolutePath, expiryISO, expiryMinutes, fullFile, startTime, startTimeEpochMs, streamId, type:"replay"}` | `{videoUrl}` only | **PARITY** on `videoUrl`, extra real fields (minor) |
| `GET /live/stream/{id}/picture` (unknown stream) | 400 `{error_code:"InvalidParameterError",…"Stream Not Found"}` | 200 placeholder JPEG always | healthy-path unverified without a live source; error envelope differs |
| `GET /replay/stream/{id}/picture?startTime=<UTC>` | 200 real 1920×1080 JPEG (verified bytes) | 200 placeholder JPEG | **PARITY** (content-type + JPEG bytes) |
| `POST /vst/api/v1/sensor/add` `{sensorUrl,name}` | 200 `{sensorId: uuid}` | 200 `{sensorId: derived}` | **PARITY** on keys |
| `GET /sensor/streams` (populated) | `{id:[{isMain, metadata:{bitrate,codec,framerate,govlength,resolution}, name, storageLocation:"Local", streamId, type:"Rtsp", url:"", vodUrl:""}]}` | `{id:[{name, url, isMain, vodUrl, type, storageLocation, metadata:{filename, createdAt}}]}` | **GAP P11** — same outer shape, different field sets (live has codec metadata + empty url/vodUrl for RTSP) |
| `DELETE /vst/api/v1/sensor/{id}` | 200 `true` | 204 empty | **GAP P12** — status + body |
| `PUT /storage/file/{f}[/{ts}]` legacy variants | not probed (POST-multipart path verified instead) | canned 200s | still unverified |

Sensor add→streams→delete cycle leaves VST clean (verified `[]`).

### 7d. Agent RTSP routes with VST up

- `POST /api/v1/rtsp-streams/add` with `{"url":…}` (wrong key) → 422
missing `sensorUrl`; mock requires `sensorUrl` too — **parity**.
- With correct `{"sensorUrl":"rtsp://127.0.0.1:8554/…","name":…}`
(unreachable camera) → 500 text `Internal Server Error`; agent log
shows a VST-validation retry storm (`RTSP URL is not valid`, empty
value) before giving up. Mock returns 200 JSON success
unconditionally — **GAP P13**: error envelope (500 text vs JSON) and
unconditional success; a true healthy add needs a live RTSP source,
still unverified. (The empty value in the validator message is
suspicious — possibly the validator reading VST's empty `url` field
back — noted as an observation, not diagnosed.)
- `DELETE /api/v1/rtsp-streams/delete/{name}` → 200
`{status:"partial", message:"…partially deleted…", name}` — keys
match the mock's `DeleteStreamResponse`; `"partial"` for a
never-registered name matches mock semantics.
- `WS /websocket`: handshake 101 as in §4; full HITL round-trip still
unverified (no ws client module on the VM; LLM now alive so a future
scripted client could close this).

### 7e. Incident-console pages + DB layer verdict

- Console pages re-verified after reboot: `/`, `/1_Catalog`,
`/2_Report_Review`, `/3_Dashboard`, `/4_Severity_Eval`,
`/_stcore/health` all 200. (R2 catalog/playback from §5 not re-probed;
reboot does not affect it.)
- `sqlalchemy` is **not** importable with system `python` in
`vss-incident-console`; the app runs under `uv run` (`/app/.venv`).
DB probes must use `docker exec … uv run --no-sync python`.
- Per firstmate steer the DSN value was never read (env-name listing
and opaque-env use only); the laptop already proved DSN + Supabase
side healthy. VM network-path diagnosis, by layer:
  - DNS: OK (`getent hosts` resolves the Supabase pooler host to 3 ELB
IPs from kwanz-ws).
  - TCP: OK (`nc -zv <pooler-host> 5432` succeeds).
  - ICMP: fully blocked both sizes (no MTU conclusion possible).
  - Postgres handshake: **FAILS** — `psycopg2` via the console's own
venv times out at both 10 s and 30 s `connect_timeout` on all 3 IPs,
while TCP SYN succeeds. So the stall is above L4: the Postgres
startup/SSL handshake never completes from the VM.
  - Verdict: not DNS, not a TCP block, not a wrong value — VM-egress
or middlebox behavior toward the pooler (e.g. DPI/MSS interference
with non-HTTP TLS). Needs the network owner / captain: check egress
policy for kwanz-ws → Supabase pooler host:5432 at L7, or try from
another host in the same net. Postgres writes/reads remain
**UNVERIFIED** live; seed stays unrunnable until this clears.
No password, key, or DSN string appears anywhere in this report or
the repo.
