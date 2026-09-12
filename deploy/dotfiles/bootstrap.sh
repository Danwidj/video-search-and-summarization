#!/usr/bin/env bash
# Idempotent, per-account dotfiles/QoL bootstrap for kwanz-ws (shared
# multi-user Ubuntu VM). Opt-in: run this from your OWN account only.
# It never touches another account's files. See README.md.
#
# Safe to re-run any time — re-running just refreshes the managed files
# and never duplicates the .bashrc include line.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOTFILES_DIR="$HOME/.vss-dotfiles"
APT_PACKAGES=(fzf ripgrep bat btop direnv)

echo "[bootstrap] Installing apt packages (skipping any already present)..."
missing=()
for pkg in "${APT_PACKAGES[@]}"; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "[bootstrap] Missing: ${missing[*]} — installing (needs sudo; this is shared infra, installed once for the whole box)..."
  sudo apt-get update -qq
  sudo apt-get install -y "${missing[@]}"
else
  echo "[bootstrap] All apt packages already present."
fi

# apt doesn't package starship for jammy — official curl installer.
# Check via a real interactive shell (`bash -ic`), not a bare `which` in
# this script's own non-interactive subshell: PATH only picks up
# ~/.local/bin once .bashrc has been sourced, so a naive `command -v
# starship` here would false-negative against an install that's already
# in place and try to reinstall it every run.
if bash -ic 'command -v starship' >/dev/null 2>&1; then
  echo "[bootstrap] starship already installed."
else
  echo "[bootstrap] Installing starship..."
  curl -sS https://starship.rs/install.sh | sh -s -- -y -b "$HOME/.local/bin"
fi

# apt doesn't package git-delta for jammy either (only noble/24.04+) — same
# no-sudo, per-account GitHub-binary-release pattern as starship above:
# extract straight into ~/.local/bin rather than a system-wide dpkg -i, since
# this is opt-in per account, not infra installed once for the whole box.
DELTA_VERSION="0.18.2"
mkdir -p "$HOME/.local/bin"
if [ -x "$HOME/.local/bin/delta" ]; then
  echo "[bootstrap] delta already installed."
else
  arch="$(uname -m)"
  case "$arch" in
    x86_64) delta_target="x86_64-unknown-linux-gnu" ;;
    aarch64) delta_target="aarch64-unknown-linux-gnu" ;;
    *)
      echo "[bootstrap] Unsupported arch '$arch' for delta — skipping (install manually if needed)." >&2
      delta_target=""
      ;;
  esac
  if [ -n "$delta_target" ]; then
    echo "[bootstrap] Installing git-delta $DELTA_VERSION..."
    delta_tmp="$(mktemp -d)"
    curl -sSL "https://github.com/dandavison/delta/releases/download/${DELTA_VERSION}/delta-${DELTA_VERSION}-${delta_target}.tar.gz" \
      | tar -xz -C "$delta_tmp"
    cp "$delta_tmp/delta-${DELTA_VERSION}-${delta_target}/delta" "$HOME/.local/bin/delta"
    rm -rf "$delta_tmp"
  fi
fi

if [ -x "$HOME/.local/bin/delta" ]; then
  echo "[bootstrap] Configuring git to use delta (per-account, via git config --global)..."
  git config --global core.pager delta
  git config --global interactive.diffFilter "delta --color-only"
  git config --global delta.navigate true
  git config --global delta.line-numbers true
fi

echo "[bootstrap] Installing managed config files..."
mkdir -p "$HOME/.config" "$DOTFILES_DIR"
cp "$SCRIPT_DIR/starship.toml" "$HOME/.config/starship.toml"
cp "$SCRIPT_DIR/shellrc.sh" "$DOTFILES_DIR/shellrc.sh"
cp "$SCRIPT_DIR/aliases.sh" "$DOTFILES_DIR/aliases.sh"

BEGIN_MARKER="# >>> vss-dotfiles >>>"
END_MARKER="# <<< vss-dotfiles <<<"
BASHRC="$HOME/.bashrc"
touch "$BASHRC"

if grep -qF "$BEGIN_MARKER" "$BASHRC"; then
  echo "[bootstrap] .bashrc already has the vss-dotfiles include block."
else
  echo "[bootstrap] Appending vss-dotfiles include block to .bashrc..."
  {
    echo ""
    echo "$BEGIN_MARKER"
    echo "[ -f \"$DOTFILES_DIR/shellrc.sh\" ] && source \"$DOTFILES_DIR/shellrc.sh\""
    echo "$END_MARKER"
  } >> "$BASHRC"
fi

echo "[bootstrap] Done. Start a new shell (or 'source ~/.bashrc') to pick up the changes."
