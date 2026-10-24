# Incident Console v2

The Next.js web console for the incident profile: upload a clip, run the VLM analysis, review and edit the report as versions, mark one official, search incidents and evidence in `/library`, and ask questions about a report.

## Run it

From `deploy/docker/developer-profiles/dev-profile-incident/`:

```bash
./start.sh --mode mock   # mock backend and VLM gateway on this laptop
./start.sh --mode vm     # the agent on kwanz-ws over an SSH tunnel
```

Either way the console opens on `http://127.0.0.1:3200`; `GET /api/health` should report `ready`. To run it by hand, start the [mock backend](../mock-backend/base_profile_mock/README.md) and the [VLM gateway](../vlm-gateway/README.md), then `npm install && npm run dev` here. Evidence frames and crops need `ffmpeg` on your PATH.

Settings come from `.env.local`, a symlink to the profile's shared `../.env.local`; edit that file, not the symlink.

## Check it

```bash
npm run lint        # Biome lint and format check, then tsc --noEmit
npm run typecheck
npm test            # tests/*.test.mjs and src/**/*.test.mjs, including the import-boundary check
npm run format      # apply the Biome formatter
```

Tests need a Node.js with TypeScript type stripping (official Node 22+ builds); where it is missing (`ERR_NO_TYPESCRIPT`), run them with `npx -y node@22`.

## Learn more

- Pages, configuration, routes and report versions: [`../.docs/architecture.md`](../.docs/architecture.md#4-runtime-interaction-sequences)
- Code layout and import rules: [`../.docs/mvp2/console-hexagonal-architecture.md`](../.docs/mvp2/console-hexagonal-architecture.md)
- Analysis contract, validation and stored attempts: [`../.docs/analysis-schema.md`](../.docs/analysis-schema.md)
- Tables and R2 keys: [`../.docs/data.md`](../.docs/data.md)
