#!/usr/bin/env bash
# Managed by deploy/dotfiles/bootstrap.sh — re-running the bootstrap
# overwrites this file, so make edits upstream in the repo, not here.
#
# Sourced by shellrc.sh. Every mdx-* wrapper below is annotated with the
# doc or script it's grounded in — check that source before assuming an
# alias's behavior if the underlying tooling has since changed.

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

# --- NGC credentials: opt-in, not auto-sourced -----------------------------
# /srv/rise-up/.ngc_env is a shared NVIDIA/NGC credential file for the whole
# smu-rise-up group's single checkout — auto-sourcing it into every login
# shell would silently export a shared credential the moment anyone runs
# this bootstrap. Call `ngc-env-on` yourself when you actually need it.
ngc-env-on() {
  local ngc_env="${VSS_NGC_ENV:-/srv/rise-up/.ngc_env}"
  if [ -f "$ngc_env" ]; then
    # Plain `source` only sets shell variables in *this* shell — it does not
    # export them, so dev-profile.sh/NGC tooling run as a child process would
    # still see no credential. `set -a`/`set +a` is this repo's own
    # documented way to source it (docs/incident-plan/incident-plan-overview.md);
    # save/restore any prior allexport state rather than assuming it was off.
    local _had_allexport=0
    case "$-" in *a*) _had_allexport=1 ;; esac
    set -a
    # shellcheck disable=SC1090
    source "$ngc_env"
    [ "$_had_allexport" -eq 1 ] || set +a
    echo "ngc-env-on: sourced $ngc_env (exported)"
  else
    echo "ngc-env-on: $ngc_env not found (set VSS_NGC_ENV to override)" >&2
    return 1
  fi
}

# --- Deploy lifecycle -------------------------------------------------------
# Every profile's compose stack shares COMPOSE_PROJECT_NAME=mdx (confirmed:
# skills/vss-deploy-profile/references/teardown.md), so the project-name-
# scoped commands below work regardless of which of the four profiles
# (base/search/lvs/alerts) is currently up — no profile argument needed for
# them. Override VSS_REPO_ROOT if your checkout isn't the shared one.
VSS_REPO_ROOT="${VSS_REPO_ROOT:-/srv/rise-up/vss}"

# Status check. Direct `docker compose -p mdx ...` — stable, generic Compose
# surface, not project deploy-script surface, so no wrapper needed. Functions
# (not aliases) so they can `cd` into deploy/docker in a subshell first:
# `compose.yml` (with its `include:` of services/developer-profiles/
# industry-profiles) only resolves via Compose's default discovery from that
# directory — dev-profile.sh's own state_up `cd`s there for the same reason
# before invoking `docker compose` (deploy/docker/scripts/dev-profile.sh) —
# so running these from any other cwd (e.g. straight after login, from
# $HOME) would otherwise fail with "no configuration file provided". The
# subshell keeps the `cd` from changing the caller's actual shell directory.
mdx-ps() {
  ( cd "$VSS_REPO_ROOT/deploy/docker" && docker compose -p mdx ps )
}

# Stop the stack WITHOUT wiping the model-weight cache. Deliberately never
# `-v`: dev-profile.sh's own `down` runs `docker compose -p mdx down -v
# --remove-orphans` and then deletes the whole data directory, which is
# exactly the ~35GB-of-NIM/RTVI-cache-loss behavior this project's own docs
# tell you to avoid — see docs/incident-plan/incident-plan-overview.md
# ("Never run `dev-profile.sh down`") and
# skills/vss-deploy-profile/references/teardown.md's cache-preserving
# teardown, whose exact `docker compose -p mdx down --remove-orphans` this
# mirrors. Direct compose function, not a dev-profile.sh wrapper, precisely
# because the safe behavior here means NOT calling dev-profile.sh's `down`.
# Same subshell-`cd` reasoning as mdx-ps above.
mdx-down() {
  ( cd "$VSS_REPO_ROOT/deploy/docker" && docker compose -p mdx down --remove-orphans )
}

# Cross-profile deploy health check. Every profile runs the agent and must
# answer on :8000/health (skills/vss-deploy-profile/references/readiness.md
# Step 2 "Cross-profile gate"; same probe listed per-profile in alerts.md).
alias mdx-health='curl -sf --max-time 15 http://localhost:8000/health && echo "agent ok"'

# Tail logs for one container (default: vss-agent, the one service every
# profile runs). Pattern matches the per-service `docker logs <name>` calls
# documented throughout skills/vss-deploy-profile/references/*.md debugging
# sections (e.g. base.md: vss-vios-ingress, vss-vios-postgres; alerts.md:
# vss-rtvi-vlm, vss-alert-bridge).
mdx-logs() {
  docker logs -f --tail=100 "${1:-vss-agent}"
}

# Disk/volume usage. Plain `docker system df` — worth having given the
# model-weight cache is exactly what mdx-down/mdx-rebuild are designed to
# avoid silently deleting; use this to see how much space it's actually
# using before deciding to reclaim it (see teardown.md's "Full teardown").
alias mdx-disk='docker system df -v'

# Fast single-service rebuild (no full stack teardown/redeploy). Direct
# compose invocation — documented pattern, not a dev-profile.sh flag:
# docs/incident-plan/incident-plan-implementation-local.md and -remote.md
# both call out `docker compose up -d --build vss-agent` for a quick agent
# rebuild and `docker compose up -d --force-recreate <vios-service>` for
# VIOS (no in-container dev-server mode for either).
#
# Unlike mdx-ps/mdx-down, this actually recreates containers, so it needs
# the currently-up profile's real config (image tags, device IDs, ...) —
# not just the project label. `dev-profile.sh up` writes exactly one
# developer-profiles/dev-profile-*/generated.env at a time (state_down
# deletes all of them first), so whichever one exists is the active
# profile; same `cd`-into-deploy/docker reasoning as mdx-ps for resolving
# compose.yml's `include:`.
mdx-rebuild-svc() {
  if [ -z "$1" ]; then
    echo "usage: mdx-rebuild-svc <service> [more services...]" >&2
    return 1
  fi
  local compose_dir="$VSS_REPO_ROOT/deploy/docker"
  local generated_env
  generated_env="$(command ls "$compose_dir"/developer-profiles/dev-profile-*/generated.env 2>/dev/null | head -1)"
  if [ -z "$generated_env" ]; then
    echo "mdx-rebuild-svc: no active profile found (no generated.env under" >&2
    echo "  $compose_dir/developer-profiles/) — is a profile currently up via dev-profile.sh?" >&2
    return 1
  fi
  ( cd "$compose_dir" && docker compose --env-file "$generated_env" -p mdx up -d --build --force-recreate "$@" )
}

# Full profile rebuild/redeploy — thin wrapper around the project's own
# canonical deploy script (deploy/docker/scripts/dev-profile.sh), not a
# hand-rolled docker/compose invocation, because THE DEPLOY COMMAND WILL
# CHANGE OVER TIME: when dev-profile.sh's flags change, only this one
# wrapper needs updating, not everyone's muscle memory.
#
# `dev-profile.sh up --profile <base|search|lvs|alerts> ...` already runs
# `docker compose up --detach --force-recreate --build` internally, so this
# IS the project's rebuild/reinstall-image command — see
# deploy/docker/scripts/dev-profile.sh (state_up/state_down) and the
# worked examples in docs/incident-plan/incident-plan-overview.md.
#
# WARNING (grounded in dev-profile.sh's own state_down, run internally
# before every `up`): this tears the existing stack down WITH -v and
# deletes the whole data directory first — same ~35GB-cache-loss behavior
# mdx-down exists to avoid. There is no "rebuild images only" mode in the
# script today; this wrapper does not invent one, it just says so loudly.
mdx-rebuild() {
  if [ -z "$1" ]; then
    echo "usage: mdx-rebuild --profile <base|search|lvs|alerts> [dev-profile.sh options...]" >&2
    echo "  (see: $VSS_REPO_ROOT/deploy/docker/scripts/dev-profile.sh --help)" >&2
    return 1
  fi
  echo "mdx-rebuild: dev-profile.sh up tears down the stack WITH -v (wipes the" >&2
  echo "model-weight cache) before rebuilding — see this function's comment in" >&2
  echo "aliases.sh." >&2
  # Explicit prompt, not a "Ctrl-C to abort" countdown: a Ctrl-C during a
  # plain `sleep` doesn't reliably abort the rest of a shell function (the
  # sleep's own interrupted exit status was never even checked here), so a
  # would-be abort could silently fall through into the destructive `up`.
  local _confirm
  read -r -p "Proceed and wipe the model-weight cache? [y/N] " _confirm
  case "$_confirm" in
    y|Y|yes|YES) ;;
    *) echo "mdx-rebuild: aborted." >&2; return 1 ;;
  esac
  "$VSS_REPO_ROOT/deploy/docker/scripts/dev-profile.sh" up "$@"
}

# On-disk data-dir cleanup between deploys/profile switches — thin wrapper
# around the project's own cleanup script (not a hand-rolled rm -rf), same
# "deploy command changes over time" reasoning as mdx-rebuild. Resolves
# generated.env (falling back to .env pre-first-deploy) exactly as
# documented in skills/vss-deploy-profile/references/teardown.md Step 0b,
# and requires passwordless sudo per that doc's gate (never runs privileged
# cleanup any other way).
mdx-clean-datalog() {
  local profile="$1"
  case "$profile" in
    base|search|lvs|alerts) ;;
    *)
      echo "usage: mdx-clean-datalog <base|search|lvs|alerts>" >&2
      return 1
      ;;
  esac
  local profile_dir="$VSS_REPO_ROOT/deploy/docker/developer-profiles/dev-profile-${profile}"
  local env_file="$profile_dir/generated.env"
  [ -f "$env_file" ] || env_file="$profile_dir/.env"
  if [ ! -f "$env_file" ]; then
    echo "mdx-clean-datalog: no env file found under $profile_dir" >&2
    return 1
  fi
  if sudo -n true 2>/dev/null; then
    sudo bash "$VSS_REPO_ROOT/deploy/docker/scripts/cleanup_all_datalog.sh" --env-file "$env_file"
  else
    echo "mdx-clean-datalog: sudo needs a password — run this once yourself:" >&2
    echo "  sudo bash $VSS_REPO_ROOT/deploy/docker/scripts/cleanup_all_datalog.sh --env-file $env_file" >&2
    return 1
  fi
}

# One-shot GPU status, on demand — not a starship module. Starship has no
# built-in nvidia module, and the only way to add one is a [custom.gpu]
# shell-out on *every* prompt render (tens-to-100+ ms latency for info
# that's usually stale by the time it's read). This alias gives the same
# info with zero per-prompt cost.
alias gpu='nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv'
