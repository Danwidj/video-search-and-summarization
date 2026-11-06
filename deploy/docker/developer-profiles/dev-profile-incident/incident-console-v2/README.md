# Incident console

The Next.js web console for the incident profile. Upload a clip, run the VLM analysis, review and edit the report as versions, mark one official, search incidents and evidence in `/library`, and ask questions about a report.

## Run it

From the profile folder (`deploy/docker/developer-profiles/dev-profile-incident/`):

```bash
./start.sh --mode vm   # the agent on kwanz-ws over an SSH tunnel
```

The console opens on `http://127.0.0.1:3200`; `GET /api/health` should report `ready`.
- **Backend:** in vm mode the console reaches only the agent (`localhost:8000`, the one tunnelled port) and uploads straight to R2 through `/api/uploads/r2`. It uses no VST and no `:7777` proxy.
- **Mock mode:** `./start.sh --mode mock` runs a zero-GPU mock that mimics the backend, a backup rather than the real one; verify UI work on the VM. To run the console by hand in mock mode, start the [mock backend](../mock-backend/base_profile_mock/README.md) and the [VLM gateway](../vlm-gateway/README.md), then `npm install && npm run dev` here.
- **Settings:** `.env.local` is a symlink to the profile's shared `../.env.local`. Edit that file, not the symlink.
- **ffmpeg:** every upload is probed and, unless it is already an H.264 MP4, converted to one at its original resolution; evidence frames and crops also need `ffmpeg`. `npm install` fetches both binaries. The console uses `FFMPEG_PATH` or `FFPROBE_PATH` first, then the bundled copy, then `PATH` ([host-binaries.ts](src/lib/video/host-binaries.ts)).
- **Evidence image (Edit mode):** clicking an evidence card's image opens a picker: choose a frame of the report's video, drag a crop with the mouse, **Use this image**. Save as new version cuts it on the server (`image_pick`, with `ffmpeg`) and stores it as that item's image; the text and track stay ([console reference](../.docs/console-reference.md#report-versions-view-edit-and-history)).
- **Background jobs:** a loop in this console's server process runs queued analyses one at a time. Every console pointed at finals takes jobs from the same queue; set `ANALYSIS_JOB_LOOP=off` to keep this one out.

## Check it

```bash
npm run lint        # Biome lint and format check, then tsc --noEmit
npm run typecheck
npm test            # tests/*.test.mjs and src/**/*.test.mjs, including the import-boundary check
npm run format      # apply the Biome formatter
```

Tests need Node.js with TypeScript type stripping (official Node 22+ builds). Where it is missing (`ERR_NO_TYPESCRIPT`), run them with `npx -y node@22`.

## Add a shadcn component

The screens are built on [shadcn/ui](https://ui.shadcn.com) (Radix, `radix-vega` preset) on Tailwind 4 and React 19, with the primitives in `src/components/ui/`. Some feature components stay custom: the video player and overlays, the versions graph and the evidence cards. Add new UI from shadcn first. Run from this folder, because the CLI reads `components.json` here:

```bash
npx shadcn@latest add <component>     # writes src/components/ui/<component>.tsx
npx shadcn@latest docs <component>    # usage and examples
```

- **Theme:** CSS variables in `src/app/styles.css`, light only. The console's own colours, fonts and `shadow-panel` sit in the `@theme` block of the same file; there is no `tailwind.config.js`.
- **Radius and font:** `rounded-*` keeps Tailwind's stock scale and the font is Arial. Changing either restyles every screen.
- **Providers:** `layout.tsx` mounts `<Toaster position="top-center" />` but no `TooltipProvider`; mount one before using `Tooltip`.
- **Format:** keep `src/components/ui/` in the repo's Biome style with `npm run format`.

## Read more

- [Console reference: Pages](../.docs/console-reference.md#console-pages): pages, routes and configuration
- [Console reference: Background analysis jobs](../.docs/console-reference.md#background-analysis-jobs): queue, claim, retry, cancel
- [Architecture: The console](../.docs/architecture.md#level-2-the-console): containers, runtime and deployment
- [Console layout](../.docs/mvp2/console-hexagonal-architecture.md): code layout and import rules
- [Analysis schema](../.docs/analysis-schema.md): contract, validation and stored attempts
- [Data layer](../.docs/data.md): tables and R2 keys
- [shadcn skill](../skills/shadcn/SKILL.md): read it before UI work
