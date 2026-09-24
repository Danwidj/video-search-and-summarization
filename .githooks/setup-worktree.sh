#!/bin/bash
# setup-worktree.sh: shared working-tree setup for the VSS repo.
#
# Invoked by .githooks/post-checkout, .githooks/post-merge and
# .githooks/post-rewrite so every working-tree-changing event runs the same
# three steps. Together those three hooks cover: git worktree add, branch
# switch, plain checkout, merge/pull, rebase and amend. (A pathspec checkout
# such as `git checkout -- <path>` also fires post-checkout on modern git -
# verified on git 2.54.0 - which is harmless here: with nothing to do the
# script is a silent no-op apart from the venv up-to-date notice.)
#
# Part 0 (dev-profile-incident root seed): in every worktree including the
# main one, if deploy/docker/developer-profiles/dev-profile-incident/.env.local
# does not exist, seed it from the tracked .env template (blank/placeholder
# values, ready for the developer to fill in). Never overwrites an existing file.
#
# Part A propagates real (non-generated) .env files and symlinks from the MAIN
# worktree into this worktree, copy-if-missing only, never overwriting. Covers the
# committed dev-profile-*/.env and industry-profile .env templates plus any
# untracked secret carriers that appear in the main worktree later
# (dev-profile-incident/.env.local, service-level .env.local symlinks,
# UI .env.local). Deliberately excludes generated.env (gitignored,
# regenerated fresh by dev-profile.sh on every deploy).
#
# Part B (dev-profile-incident symlink self-heal): in every worktree including
# the main one, explicitly verify each of the 3 known subfolder paths
# (incident-console/.env.local, incident-console-v2/.env.local,
# vlm-gateway/.env.local) is a symlink pointing at ../.env.local. If a path is
# missing, is a real file, or points anywhere else, replace it with the correct
# relative symlink. Log one line per path fixed.
#
# Part C ensures the incident-console uv venv exists and is in sync
# (uv sync creates .venv on first run). Unlike Part A it also runs in the
# main worktree itself - the main worktree is the .env source but still
# needs its own venv. Skips the (slow, networked) sync when .venv is newer
# than pyproject.toml and uv.lock.
#
# This script must NEVER fail the calling git command: every best-effort
# step warns and continues, and the script always exits 0, so a broken env
# never blocks a checkout, merge or rebase.

set -uo pipefail

main_worktree=$(git worktree list --porcelain | head -1 | sed 's/^worktree //')
current_dir=$(git rev-parse --show-toplevel)

INCIDENT_ROOT="deploy/docker/developer-profiles/dev-profile-incident"
incident_root_dir="$current_dir/$INCIDENT_ROOT"

# --- Part 0: dev-profile-incident root .env.local seed (runs in ALL worktrees).
if [ -d "$incident_root_dir" ] && [ -f "$incident_root_dir/.env" ] && [ ! -e "$incident_root_dir/.env.local" ]; then
    cp "$incident_root_dir/.env" "$incident_root_dir/.env.local"
    echo "setup-worktree: seeded $INCIDENT_ROOT/.env.local from .env template"
fi

# --- Part A: .env propagation (no-op inside the main worktree itself,
# --- which is the copy source, not a destination).
if [ "$current_dir" != "$main_worktree" ]; then
    find "$main_worktree" \
        \( -name node_modules -o -name .venv -o -name .git -o -path '*/.git/*' \) -prune -o \
        \( -name '.env' -o -name '.env.*' -o -name '*.env_file' \) \( -type f -o -type l \) -print |
    while read -r src; do
        rel="${src#"$main_worktree"/}"
        dest="$current_dir/$rel"
        if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then
            mkdir -p "$(dirname "$dest")"
            if [ -L "$src" ]; then
                ln -s "$(readlink "$src")" "$dest"
            else
                cp "$src" "$dest"
            fi
            echo "setup-worktree: copied $rel"
        fi
    done
fi

# --- Part B: dev-profile-incident symlink self-heal (runs in ALL worktrees).
if [ -d "$incident_root_dir" ]; then
    for sub in incident-console incident-console-v2 vlm-gateway; do
        target="$incident_root_dir/$sub/.env.local"
        # Check if target exists and is a symlink pointing to ../.env.local
        need_fix=0
        if [ ! -e "$target" ] && [ ! -L "$target" ]; then
            need_fix=1
        elif [ -L "$target" ]; then
            link_target=$(readlink "$target")
            if [ "$link_target" != "../.env.local" ]; then
                need_fix=1
            fi
        else
            # Exists but is not a symlink (regular file or other)
            need_fix=1
        fi
        if [ "$need_fix" -eq 1 ]; then
            rm -f "$target"
            ln -s "../.env.local" "$target"
            echo "setup-worktree: fixed symlink $INCIDENT_ROOT/$sub/.env.local -> ../.env.local"
        fi
    done
fi

# --- Part C: incident-console uv venv.
CONSOLE_REL="deploy/docker/developer-profiles/dev-profile-incident/incident-console"
console_dir="$current_dir/$CONSOLE_REL"
if [ -f "$console_dir/pyproject.toml" ]; then
    if ! command -v uv >/dev/null 2>&1; then
        echo "setup-worktree: WARNING: uv not found, skipping incident-console venv setup" >&2
    else
        venv_dir="$console_dir/.venv"
        up_to_date=0
        if [ -d "$venv_dir" ] && [ "$venv_dir" -nt "$console_dir/pyproject.toml" ]; then
            if [ ! -f "$console_dir/uv.lock" ] || [ "$venv_dir" -nt "$console_dir/uv.lock" ]; then
                up_to_date=1
            fi
        fi
        if [ "$up_to_date" -eq 1 ]; then
            echo "setup-worktree: incident-console .venv up to date, skipping uv sync"
        else
            echo "setup-worktree: running uv sync for incident-console..."
            if (cd "$console_dir" && uv sync); then
                # Mark the venv fresh: a no-change sync leaves .venv's mtime
                # older than pyproject.toml/uv.lock, which would otherwise
                # re-trigger a (fast but noisy) sync on every future event.
                touch "$venv_dir"
                echo "setup-worktree: uv sync complete"
            else
                echo "setup-worktree: WARNING: uv sync failed, continuing" >&2
            fi
        fi
    fi
fi

exit 0
