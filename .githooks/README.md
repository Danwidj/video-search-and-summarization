# Git hooks (`.githooks/`)

Automatic environment setup that fires on every working-tree-changing event.
Activate once per clone:

```
.githooks/activate.sh   # sets core.hooksPath=.githooks (local config)
```

## What fires when

| Event | Hook | Runs |
|---|---|---|
| `git worktree add`, branch switch, plain `git checkout <sha>` | `post-checkout` | shared setup + `git lfs post-checkout` |
| `git merge`, `git pull` | `post-merge` | shared setup + `git lfs post-merge` |
| `git rebase`, `git commit --amend` | `post-rewrite` | shared setup |
| `git commit` | `post-commit` | stock LFS shim only |
| `git push` | `pre-push` | stock LFS shim only |

`git checkout -- <path>` (pathspec restore) also fires `post-checkout` on
modern git (verified on 2.54.0) - harmless here, the script is a no-op when
the env is current.

## Shared setup (`setup-worktree.sh`)

1. **`.env` propagation.** Copies `.env` / `.env.*` / `*.env_file` files
   found in the main worktree (pruning `node_modules`, `.venv`, `.git`)
   into the same relative path here, but only when the destination file
   does not already exist - never overwrites. No-ops inside the main
   worktree itself (the copy source). `generated.env` never matches the
   patterns and is never copied.
2. **incident-console uv venv.** Runs `uv sync` in
   `deploy/docker/developer-profiles/dev-profile-incident/incident-console`
   (which creates `.venv` on first run), skipped when `.venv` is newer
   than `pyproject.toml` and `uv.lock`. Warns and continues when `uv` is
   missing or `uv sync` fails - a broken env never blocks a git operation.

The git-lfs invocations are preserved from the original VM hook; on
machines without `git-lfs` they warn instead of failing the git command.

## Out of scope (separate tracked phases)

direnv / `.ngc_env` integration and R2 config are not handled here.

## G10 constraint (Phase 5 env plan)

The `.env` propagation above copies real-value files (including
`incident-console/.env.local`) into every new/checked-out worktree. That is
accepted on a personal laptop, where all worktrees belong to one operator. On the
shared VM it would spray one account's live Supabase/R2 credentials across
per-account worktrees, so propagation there must stay laptop-only: on the shared
box prefer per-account shell exports over a shared-checkout `.env.local`, and do
not extend this script to propagate real-value env files across worktrees.
