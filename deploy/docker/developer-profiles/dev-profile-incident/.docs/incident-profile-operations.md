# Incident profile operations

The profile README is the human-facing entry point and owns secrets. This file
contains only deployment topology and operational facts that an AI needs when
changing or troubleshooting the profile.

## Repository layout

- `compose.yml`: profile include for the profile-owned services.
- `incident-console/`: Streamlit v1 console and evaluation tools.
- `incident-console-v2/`: Next.js v2 console; current primary UI.
- `mock-backend/`: zero-GPU base/search backend mocks.
- `vlm-gateway/`: server-side credential-holding inference proxy.
- `supabase/migrations/`: runtime RPC migration for atomic incident writes.
- `.scripts/`: VM lifecycle, native-service, tunnel, and health scripts.
- `start.sh`: laptop entry point for v2 local or VM mode.

## Runtime topology

Both consoles run on the developer laptop. VM mode reaches `kwanz-ws` through
an SSH tunnel. Local mode starts the base mock backend on `127.0.0.1:7777` and
the VLM gateway on `127.0.0.1:8600`; v2 runs on port 3200.

On `kwanz-ws`:

- Native: `vss-agent` on port 8000; optional
  `video-analytics-api` on 8081 and `behavior-analytics` on 8080.
- Docker: VIOS stream processing/NvStreamer/ingress, internal Postgres,
  Redis, Phoenix, and—when analytics is enabled—Elasticsearch and Kafka.

Use `.scripts/native-services.sh` for native processes. Do not start a second
agent container when the native agent is active.

## Safe operations

- The incident profile is not a `dev-profile.sh` profile. Use the root
  `deploy/docker/compose.yml` with the active generated environment file.
- `dev-profile.sh down` is destructive (`down -v` plus data cleanup). Use
  `.scripts/down.sh` or plain `docker compose down`.
- Restart native agent code with:

  ```bash
  .scripts/native-services.sh restart vss-agent
  ```

- Rebuild a Docker appliance only when its source changed; native source
  changes need a restart, not an image rebuild.
- Keep `generated.env.local` and `generated.env.remote` untracked. Never put
  credentials in `.env`, images, or client-exposed `NEXT_PUBLIC_*` variables.

## VM connectivity

The standard tunnel forwards the agent (`8000`), local inference ports
(`30081`/`30082` when applicable), and ingress (`7777`). Use:

```bash
./.scripts/tunnel.sh
./.scripts/tunnel-check.sh
```

Use `./start.sh --mode local` for laptop-only development or
`./start.sh --mode vm` for the shared backend. VM mode must use the VM's real
`HOST_IP` for container-to-container URLs and `EXTERNAL_IP=localhost` for
browser URLs through the tunnel.

## Troubleshooting order

1. Check `.scripts/status.sh` and `.scripts/native-services.sh status`.
2. Check `.scripts/health.sh` or `curl http://localhost:8000/health`.
3. Inspect native logs with `.scripts/logs.sh vss-agent`; inspect Docker logs
   with `docker logs`.
4. Treat startup 503s as possible readiness delay before changing configuration.
5. For partial deploys, stop and reconcile manually; do not force-redeploy
   blindly over a mixed native/Docker state.
