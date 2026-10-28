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

## shadcn/ui

The console is moving to [shadcn/ui](https://ui.shadcn.com) (Radix, `radix-vega` preset) on Tailwind 4 and React 19. The primitives are installed in `src/components/ui/` but nothing uses them yet; the existing hand-written screens still use their own classes.

Add a component from this directory (the CLI reads `components.json` here; from elsewhere pass `-c <path to this directory>`):

```bash
npx shadcn@latest add <component>     # e.g. popover; writes src/components/ui/<component>.tsx
npx shadcn@latest docs <component>    # usage and examples
```

- **Theme tokens:** CSS variables in `src/app/styles.css`. Light values are in `:root`, dark values in `.dark` (toggled by a `dark` class on an ancestor, not wired up yet). `@theme inline` maps them to Tailwind colours (`bg-primary`, `text-muted-foreground`, ...). The console's own colours (`ink`, `canvas`, `signal`, `moss`, `clay`), fonts and `shadow-panel` are in the `@theme` block of the same file; there is no `tailwind.config.js`.
- **Radius and font:** the shadcn radius override is left out, so `rounded-*` keeps Tailwind's stock scale, and the font stays Arial. Changing either restyles every existing screen.
- **Provider and toaster:** `Tooltip` needs `TooltipProvider` and `sonner` needs `<Toaster />` mounted in `src/app/layout.tsx`. Neither is mounted yet.
- **Agent tooling:** the shadcn skill is in `.claude/skills/shadcn` (installed with `npx skills add shadcn/ui`, pinned in `skills-lock.json`) and the shadcn MCP server is in `.mcp.json` at the repo root. Restart Claude Code and run `/mcp` to see it connect.
- **Lint:** `src/components/ui/` is formatted to the repo's Biome style; keep that when adding components (`npm run format`).

## Learn more

- Pages, configuration, routes and report versions: [`../.docs/architecture.md`](../.docs/architecture.md#4-runtime-interaction-sequences)
- Code layout and import rules: [`../.docs/mvp2/console-hexagonal-architecture.md`](../.docs/mvp2/console-hexagonal-architecture.md)
- Analysis contract, validation and stored attempts: [`../.docs/analysis-schema.md`](../.docs/analysis-schema.md)
- Tables and R2 keys: [`../.docs/data.md`](../.docs/data.md)
