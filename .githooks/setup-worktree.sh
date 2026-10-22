#!/bin/bash
# setup-worktree.sh: shared working-tree setup for the VSS repo.
#
# Invoked by .githooks/post-checkout, .githooks/post-merge and
# .githooks/post-rewrite so every working-tree-changing event runs the same
# setup steps. Together those three hooks cover: git worktree add, branch
# switch, plain checkout, merge/pull, rebase and amend. (A pathspec checkout
# such as `git checkout -- <path>` also fires post-checkout on modern git -
# verified on git 2.54.0 - which is harmless here: with nothing to do the
# script is a silent no-op apart from the venv up-to-date notice.)
#
# Part 0 (dev-profile-incident root .env.local): a new worktree must get the
# main worktree's real deploy/docker/developer-profiles/dev-profile-incident/.env.local
# (the developer's secrets). Outside the main worktree, when the main worktree
# has that file, copy it here if the target is missing or is still a byte-exact
# copy of the placeholder .env template (what an older version of this hook
# seeded); never overwrite any other existing .env.local. Only when there is no
# real file to copy (fresh clone, or the main worktree itself) seed a missing
# .env.local from the tracked .env template instead.
#
# Part A propagates real (non-generated) .env files and symlinks from the MAIN
# worktree into this worktree, copy-if-missing only, never overwriting. Covers the
# committed dev-profile-*/.env and industry-profile .env templates plus any
# untracked secret carriers that appear in the main worktree later
# (service-level .env.local symlinks, UI .env.local; the dev-profile-incident
# root .env.local is normally already handled by Part 0). Deliberately excludes generated.env (gitignored,
# regenerated fresh by dev-profile.sh on every deploy) and everything under
# dev-profile-incident/archived/ (retired code is never set up).
#
# Part B (dev-profile-incident symlink self-heal): in every worktree including
# the main one, explicitly verify each of the 3 known subfolder paths read by
# the active services (incident-console-v2/.env.local, vlm-gateway/.env.local,
# mock-backend/.env.local) is a symlink pointing at ../.env.local. If a path is
# missing, is a real file, or points anywhere else, replace it with the correct
# relative symlink. Log one line per path fixed.
#
# No uv venv is prepared here: start.sh runs `uv sync` for mock-backend and
# vlm-gateway and `npm install` for incident-console-v2 on every launch. (The
# former Part C synced the venv of the v1 console, now archived under
# dev-profile-incident/archived/incident-console/.)
#
# This script must NEVER fail the calling git command: every best-effort
# step warns and continues, and the script always exits 0, so a broken env
# never blocks a checkout, merge or rebase.

set -uo pipefail

main_worktree=$(git worktree list --porcelain | head -1 | sed 's/^worktree //')
current_dir=$(git rev-parse --show-toplevel)

INCIDENT_ROOT="deploy/docker/developer-profiles/dev-profile-incident"
incident_root_dir="$current_dir/$INCIDENT_ROOT"

# --- Part 0: dev-profile-incident root .env.local (runs in ALL worktrees).
if [ -d "$incident_root_dir" ]; then
    target_env_local="$incident_root_dir/.env.local"
    template_env="$incident_root_dir/.env"
    main_env_local="$main_worktree/$INCIDENT_ROOT/.env.local"
    if [ "$current_dir" != "$main_worktree" ] && [ -f "$main_env_local" ]; then
        if [ ! -e "$target_env_local" ] && [ ! -L "$target_env_local" ]; then
            cp "$main_env_local" "$target_env_local"
            echo "setup-worktree: copied $INCIDENT_ROOT/.env.local from the main worktree"
        elif [ -f "$target_env_local" ] && [ ! -L "$target_env_local" ] && [ -f "$template_env" ] &&
            cmp -s "$target_env_local" "$template_env" && ! cmp -s "$target_env_local" "$main_env_local"; then
            cp "$main_env_local" "$target_env_local"
            echo "setup-worktree: replaced placeholder $INCIDENT_ROOT/.env.local with the main worktree's copy"
        fi
    elif [ -f "$template_env" ] && [ ! -e "$target_env_local" ] && [ ! -L "$target_env_local" ]; then
        cp "$template_env" "$target_env_local"
        echo "setup-worktree: seeded $INCIDENT_ROOT/.env.local from .env template"
    fi
fi

# --- Part A: .env propagation (no-op inside the main worktree itself,
# --- which is the copy source, not a destination).
if [ "$current_dir" != "$main_worktree" ]; then
    find "$main_worktree" \
        \( -name node_modules -o -name .venv -o -name .git -o -path '*/.git/*' \
           -o -path "$main_worktree/$INCIDENT_ROOT/archived" \) -prune -o \
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
    for sub in incident-console-v2 vlm-gateway mock-backend; do
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

exit 0
