# deploy/dotfiles

Personal, opt-in shell QoL setup for `kwanz-ws`, the shared multi-user
Ubuntu VM this project is deployed on. A single idempotent bash script —
not chezmoi, not a symlink farm — because this is six accounts sharing one
box, not a personal daily-driver machine.

## What it does

- Installs `fzf`, `ripgrep`, `bat` (aliased as `bat`, apt ships the binary
  as `batcat`) and `btop` via `apt` (skips anything already
  installed).
- Installs `starship` via its official curl installer (apt doesn't package
  it for jammy) and drops a config tuned for this box: username+hostname
  always visible (six accounts, one machine), directory, git branch/status,
  command duration, no GPU/docker custom module (see below).
- Installs `git-delta` (as `delta`) the same curl-binary way (apt doesn't
  package it for jammy either — only 24.04+), straight into `~/.local/bin`
  with no `sudo`, and wires it into **your own** `git config --global`
  (`core.pager`, `interactive.diffFilter`, navigate/line-numbers) — an
  opt-in per-account config, not a box-wide git setting.
- Aliases `vim` to the system-wide `/opt/nvim` (already on `PATH`, no apt
  package needed), `htop` to `btop`, and `cat` to a paging-free `bat`; wires
  fzf's own Ctrl-R/Ctrl-T fuzzy history/file-find key bindings.
- Adds `~/.local/bin` and `/opt/nvim/bin` to `PATH`, and wires the
  starship/fzf shell hooks.
- Adds a `deploy/docker`-lifecycle alias/function set (see below).
- Appends **one** marker-guarded include block to `~/.bashrc` that sources
  the managed `shellrc.sh` — everything else lives in files this script
  overwrites on re-run, so re-running it to pick up changes never
  duplicates or hand-edits `.bashrc` again.

## Scope: opt-in, per-account

This only touches **your own** `$HOME` (`apt install` is the one
exception — package installs are shared infra regardless of who triggers
them). It is not mandatory team-wide provisioning; each teammate runs it
against their own account only if they want it.

## How to run it

The VM already has this repo checked out at `/srv/rise-up/vss`
(group-readable by `smu-rise-up`), so there's no separate clone or access
step:

```bash
bash /srv/rise-up/vss/deploy/dotfiles/bootstrap.sh
```

Then start a new shell (or `source ~/.bashrc`).

## Notable pieces

- **`ngc-env-on`** (in `aliases.sh`) — sources the shared
  `/srv/rise-up/.ngc_env` NGC/NVIDIA credential on demand. Deliberately
  **not** auto-sourced on login: `/srv/rise-up/vss` is one shared checkout
  the whole group works from their own accounts, so auto-exporting a
  shared credential into every login shell the moment someone runs this
  bootstrap is the wrong default. Call `ngc-env-on` yourself when you need it.
- **`git-delta`** — installed and wired into `git config --global` per
  account, not box-wide: each teammate who runs the bootstrap gets nicer
  diffs in their own git config, and nobody who hasn't opted in is affected.
- **`mdx-*` deploy-lifecycle aliases/functions** — wrap the project's own
  canonical deploy tooling (`deploy/docker/scripts/dev-profile.sh` and
  `cleanup_all_datalog.sh`) rather than hardcoding raw `docker`/`docker
  compose` invocations, specifically because **the deployment command will
  change over time**: when `dev-profile.sh`'s interface changes, only the
  wrapper needs updating, not everyone's muscle memory. Aliases that call a
  script are noted as such in `aliases.sh`'s own comments, next to the doc
  each one is grounded in; plain `docker compose -p mdx ...` is used only
  where there's no canonical script to wrap (status, logs, disk usage —
  stable, generic Compose surface, not project-specific tooling likely to
  drift).
- **`mdx-tunnel-incident` / `mdx-tunnel-incident-check`** (in `aliases.sh`) —
  the one exception to "this file runs on the VM": these two run on your
  **laptop**, opening (`ssh -N -L`) and proving the SSH tunnel through which
  the laptop-local incident-console reaches the real kwanz-ws backend
  (agent :8000, LLM :30081, VLM :30082) instead of the mock. Phase 4 design:
  the console never deploys to the VM; the VM runs only the backend stack.
  No `bootstrap.sh` / `shellrc.sh` change was needed for them: the bootstrap
  already copies `aliases.sh` verbatim and `shellrc.sh` already sources it,
  so the tunnel functions ship through that same channel on next re-run.
