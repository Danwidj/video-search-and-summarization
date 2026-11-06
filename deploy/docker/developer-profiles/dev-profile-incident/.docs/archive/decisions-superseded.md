# Superseded decisions

Decisions that a later entry in [`decisions.md`](../decisions.md) replaced, kept here with the original wording. Newest first.

### 2026-10-24: Chat about the official version uses the in-memory chat search client for MVP2 (superseded 2026-11-06)
- **Superseded 2026-11-06** for template mode by [template chat answers the official version from its report](../decisions.md#2026-11-06-template-chat-answers-the-official-version-from-its-report-and-citations-use-the-crops-second).
- **Superseded for grounded mode (2026-11-02):** see [Grounded chat answers from one report version](../decisions.md#2026-11-02-grounded-chat-answers-from-one-report-version-with-a-chat-model-behind-a-mode-switch-gate-m2-approved-by-the-chatbot-feature-owner). This entry still describes template mode, which remains the default.
- **Decision:** A chat question about the official revision with no draft goes to the agent chat route's search client, which stays the in-memory canned client for MVP2, so it finds no evidence for a finals video. Other versions and drafts are answered from their saved evidence.
- **Why:** A deliberate choice by the captain (2026-10-24); no reason was recorded.
- **Rejected:** none recorded.
- **Links:** [`vm-api-contracts.md`](../vm-api-contracts.md#post-apiv1incidentschat).

### 2026-10-22: Stop VM backend services on last exit via shared flock over SSH (superseded 2026-11-02)
- **Superseded 2026-11-02** by [closing `start.sh` leaves the VM backend running](../decisions.md#2026-11-02-closing-startsh-leaves-the-vm-backend-running).
- **Decision:** `start.sh --mode vm` registers active sessions by holding a shared flock on a world-writable lock file on the VM (`$VSS_REPO_ROOT/.run/active-runs.lock`) through a long-lived SSH connection with pseudo-terminal allocation (`-tt` so remote lock processes terminate when the client disconnects). If registration cannot be confirmed within 10s (e.g. while an exclusive stop lock is held during backend shutdown), `start.sh` aborts with a retry prompt rather than continuing unregistered. On exit (Ctrl+C, SIGTERM, normal exit), `start.sh` releases its shared lock and executes `.scripts/vm-stop-backend.sh` over SSH. `vm-stop-backend.sh` attempts a non-blocking exclusive flock; only when it succeeds (proving the exiting session is the last active user on the shared VM) does it stop the native services (`native-services.sh stop`) and expected Docker containers via `docker stop`. Docker containers are only stopped, never removed or deleted (`docker rm`, `compose down`, `-v` are never used). A failure to stop is non-fatal with a clear warning. Hermetic tests live in `.scripts/test-vm-stop-backend.sh`.
- **Why:** Teammates share `kwanz-ws`. Exiting `start.sh` previously left VM containers and native processes running indefinitely, consuming GPU and memory. Stopping unconditionally on Ctrl+C would disrupt teammates running concurrent sessions. Tracking active runs with a kernel-managed shared flock through a long-lived SSH session ensures that locks disappear automatically if a laptop crashes or disconnects without leaving stale state, and exclusive locking cleanly coordinates last-user shutdown.
- **Rejected:**
  - Unconditional shutdown on exit: takes the backend away from concurrent teammates.
  - Disk PID or registry files on the VM: leave stale entries after laptop crashes, killing future auto-stops.
  - `docker compose down` or `dev-profile.sh down`: removes containers and wipes model caches.
  - Server-side cron or idle timeouts: complex and disconnected from active client sessions.
- **Links:** [`../start.sh`](../../start.sh); `.scripts/vm-stop-backend.sh` and `.scripts/test-vm-stop-backend.sh` (both removed on 2026-11-02); [`incident-profile-operations.md`](../incident-profile-operations.md); [`../skills/incident-start/SKILL.md`](../../skills/incident-start/SKILL.md).
