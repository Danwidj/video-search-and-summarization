#!/usr/bin/env bash
# Managed by deploy/dotfiles/bootstrap.sh — re-running the bootstrap
# overwrites this file, so make edits upstream in the repo, not here.
#
# Sourced by shellrc.sh. This file now carries ONLY the generic shell QoL
# aliases (nothing VSS deploy-lifecycle-specific). The VSS deploy-lifecycle
# commands that used to live here (ngc-env-on, mdx-ps, mdx-down, mdx-health,
# mdx-tunnel-incident, mdx-tunnel-incident-check, mdx-logs, mdx-disk,
# mdx-rebuild-svc, mdx-rebuild, mdx-clean-datalog, gpu) moved to standalone,
# executable scripts directly under:
#
#   deploy/docker/developer-profiles/dev-profile-incident/scripts/
#
# (`status.sh`, `down.sh`, `health.sh`, `tunnel.sh`, `tunnel-check.sh`,
# `logs.sh`, `disk.sh`, `rebuild-svc.sh`, `rebuild.sh`, `clean-datalog.sh`,
# `ngc-env.sh`, `gpu.sh`, `resolve-ssh-target.sh`) plus `start.sh` at the top
# level of `dev-profile-incident/` as the one-command daily entry point. Run
# those scripts instead of shell aliases.

# apt installs bat's binary as `batcat` on Debian/Ubuntu (name collision
# with an unrelated package already called `bat`).
if command -v batcat >/dev/null 2>&1; then
  alias bat=batcat
fi

# /opt/nvim is the system-wide nvim release already on PATH via shellrc.sh
# (see AGENTS.md / README — apt's nvim on jammy is older than this box's).
if command -v nvim >/dev/null 2>&1; then
  alias vim=nvim
fi

# Drop-in syntax-highlighted replacement for `cat`. `--paging=never` avoids
# surprising anyone with a pager on a plain `cat foo`; bat/batcat already
# auto-detects non-terminal (piped/scripted) output and falls back to plain
# behavior there regardless.
if command -v bat >/dev/null 2>&1 || command -v batcat >/dev/null 2>&1; then
  alias cat="bat --style=plain --paging=never"
fi

# btop is the one actually installed by this bootstrap and is strictly
# better than htop.
if command -v btop >/dev/null 2>&1; then
  alias htop=btop
fi
