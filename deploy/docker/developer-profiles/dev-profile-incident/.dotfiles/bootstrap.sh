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
# curl is a hard prerequisite (starship and delta below are both installed by
# curl-fetching their release archives), so it's in this list even though it
# isn't otherwise part of the QoL tool set — without it the script would
# silently die partway through, after installing packages but before writing
# any managed files.
APT_PACKAGES=(curl fzf ripgrep bat btop)

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

# apt doesn't package starship for jammy — download pinned release binary with checksum.
# Set BOOTSTRAP_SKIP_STARSHIP=1 to skip.
# Check via a real interactive shell (`bash -ic`), not a bare `which` in
# this script's own non-interactive subshell: PATH only picks up
# ~/.local/bin once .bashrc has been sourced, so a naive `command -v
# starship` here would false-negative against an install that's already
# in place and try to reinstall it every run.
STARSHIP_VERSION="1.22.1"
mkdir -p "$HOME/.local/bin"
if [ "${BOOTSTRAP_SKIP_STARSHIP:-0}" = "1" ]; then
  echo "[bootstrap] BOOTSTRAP_SKIP_STARSHIP=1 — skipping starship installation."
elif bash -ic 'command -v starship' >/dev/null 2>&1; then
  echo "[bootstrap] starship already installed."
else
  arch="$(uname -m)"
  case "$arch" in
    x86_64)
      starship_target="x86_64-unknown-linux-gnu"
      starship_sha256="e57db6f6497ee8a426c5e77b4d6f5c50734d3e9cca7a18a8aef46730505a3ae7"
      ;;
    aarch64)
      starship_target="aarch64-unknown-linux-musl"
      starship_sha256="b82edd21060f3ed112460442c48a3a9545c8dbf3b564154441f4e6b58eacc387"
      ;;
    *)
      echo "[bootstrap] Unsupported arch '$arch' for starship — skipping (install manually if needed)." >&2
      starship_target=""
      starship_sha256=""
      ;;
  esac
  if [ -n "$starship_target" ]; then
    echo "[bootstrap] Installing starship $STARSHIP_VERSION ($starship_target)..."
    starship_tmp="$(mktemp -d)"
    starship_tar="${starship_tmp}/starship.tar.gz"
    curl -sSL "https://github.com/starship/starship/releases/download/v${STARSHIP_VERSION}/starship-${starship_target}.tar.gz" -o "$starship_tar"
    echo "${starship_sha256}  ${starship_tar}" | sha256sum -c -
    tar -xzf "$starship_tar" -C "$starship_tmp"
    cp "$starship_tmp/starship" "$HOME/.local/bin/starship"
    chmod +x "$HOME/.local/bin/starship"
    rm -rf "$starship_tmp"
  fi
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
# The managed aliases.sh is now QoL-only (bat/vim/cat/htop): the VSS
# deploy-lifecycle commands (old mdx-*, ngc-env-on, gpu) moved to standalone
# executable scripts under
# deploy/docker/developer-profiles/dev-profile-incident/.scripts/ (status.sh,
# down.sh, health.sh, logs.sh, rebuild-svc.sh, clean-datalog.sh, ngc-env.sh,
# gpu.sh, tunnel.sh, tunnel-check.sh, resolve-ssh-target.sh) plus start.sh
# at the top level of dev-profile-incident/
# as the one-command daily entry point. Copying the repo's aliases.sh verbatim
# keeps this regeneration from ever re-adding those removed commands — make any
# future alias changes upstream in $SCRIPT_DIR/aliases.sh, not in the
# installed copy.
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
source ~/.bashrc
