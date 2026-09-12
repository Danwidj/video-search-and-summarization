#!/usr/bin/env bash
# Managed by deploy/dotfiles/bootstrap.sh — re-running the bootstrap
# overwrites this file, so make edits upstream in the repo, not here.
#
# Sourced from ~/.bashrc via the single marker-guarded include line
# bootstrap.sh appends. Keep all eval/export/PATH logic here rather than
# inline in .bashrc, so re-running the bootstrap to pick up changes never
# has to re-edit .bashrc.

# curl-installed binaries (starship) land in ~/.local/bin; /opt/nvim is a
# system-wide nvim 0.12.4 release (yang-owned, not apt) — see AGENTS.md /
# the dotfiles README for why apt is skipped for both.
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
case ":$PATH:" in
  *":/opt/nvim/bin:"*) ;;
  *) export PATH="$PATH:/opt/nvim/bin" ;;
esac

if command -v starship >/dev/null 2>&1; then
  eval "$(starship init bash)"
fi

if command -v direnv >/dev/null 2>&1; then
  eval "$(direnv hook bash)"
fi

_vss_dotfiles_dir="$(dirname "${BASH_SOURCE[0]}")"
if [ -f "$_vss_dotfiles_dir/aliases.sh" ]; then
  # shellcheck source=aliases.sh
  source "$_vss_dotfiles_dir/aliases.sh"
fi
unset _vss_dotfiles_dir
