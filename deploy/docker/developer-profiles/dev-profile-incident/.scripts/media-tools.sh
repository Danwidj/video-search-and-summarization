#!/usr/bin/env bash
#
# media-tools.sh — ffmpeg and ffprobe for vss-agent on kwanz-ws, without a system-wide install
#
# Usage:
#   ./media-tools.sh install   # install a static build into the tools dir unless both are already on PATH
#   ./media-tools.sh check     # print where ffmpeg and ffprobe resolve from (exit 1 if either is missing)
#
# The agent's caption pass (INCIDENT_CHUNKING_ENABLED) and person tracking (INCIDENT_TRACKING_ENABLED)
# run ffmpeg and ffprobe from PATH. native-services.sh puts the tools dir first on PATH and runs
# `install` before it starts vss-agent. The tools dir is repo-local and gitignored, so it is shared by
# everyone who starts the agent from this checkout and survives a rebuilt agent venv.
#
# Environment:
#   VSS_MEDIA_TOOLS_DIR  install prefix (default <repo>/.tools/ffmpeg); binaries go in its bin/
#   VSS_FFMPEG_BUILD     BtbN FFmpeg-Builds asset name, without .tar.xz (default ffmpeg-n8.1-latest-linux64-gpl-8.1)
#   VSS_FFMPEG_BASE_URL  release download URL (default the BtbN "latest" GitHub release)

set -euo pipefail

MEDIA_TOOLS_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIA_TOOLS_REPO_ROOT="$(cd "${MEDIA_TOOLS_SCRIPT_DIR}/../../../../.." && pwd)"
VSS_MEDIA_TOOLS_DIR="${VSS_MEDIA_TOOLS_DIR:-${MEDIA_TOOLS_REPO_ROOT}/.tools/ffmpeg}"
VSS_FFMPEG_BUILD="${VSS_FFMPEG_BUILD:-ffmpeg-n8.1-latest-linux64-gpl-8.1}"
VSS_FFMPEG_BASE_URL="${VSS_FFMPEG_BASE_URL:-https://github.com/BtbN/FFmpeg-Builds/releases/download/latest}"

media_tools_bin() {
  echo "${VSS_MEDIA_TOOLS_DIR}/bin"
}

# PATH with the tools dir first, so a tools-dir build wins over anything else on PATH.
media_tools_path() {
  echo "$(media_tools_bin):${PATH}"
}

# "<tool> <path> <version>" per tool, or "<tool> MISSING"; returns 1 if either is missing.
media_tools_check() {
  local tool path version status=0
  for tool in ffmpeg ffprobe; do
    path="$(PATH="$(media_tools_path)" command -v "${tool}" 2>/dev/null || true)"
    if [ -z "${path}" ]; then
      echo "${tool} MISSING"
      status=1
      continue
    fi
    version="$("${path}" -version 2>/dev/null | head -1 | awk '{print $3}')"
    echo "${tool} ${path} ${version:-unknown}"
  done
  return "${status}"
}

# Download, verify and unpack the build in ${1} (a scratch dir), then move the two binaries into place.
_media_tools_fetch() {
  local work="$1"
  local archive="${work}/${VSS_FFMPEG_BUILD}.tar.xz"
  local expected actual tool

  echo "  Installing ${VSS_FFMPEG_BUILD} into $(media_tools_bin)..."
  if ! curl -fsSL --max-time 60 -o "${work}/checksums.sha256" "${VSS_FFMPEG_BASE_URL}/checksums.sha256" ||
    ! curl -fsSL --max-time 180 -o "${archive}" "${VSS_FFMPEG_BASE_URL}/${VSS_FFMPEG_BUILD}.tar.xz"; then
    echo "WARNING: could not download ${VSS_FFMPEG_BUILD} from ${VSS_FFMPEG_BASE_URL}" >&2
    return 1
  fi
  expected="$(awk -v name="${VSS_FFMPEG_BUILD}.tar.xz" '$2 == name {print $1}' "${work}/checksums.sha256")"
  actual="$(sha256sum "${archive}" | awk '{print $1}')"
  if [ -z "${expected}" ] || [ "${expected}" != "${actual}" ]; then
    echo "WARNING: checksum mismatch for ${VSS_FFMPEG_BUILD}.tar.xz (expected '${expected}', got '${actual}')" >&2
    return 1
  fi

  tar -xJf "${archive}" -C "${work}" "${VSS_FFMPEG_BUILD}/bin/ffmpeg" "${VSS_FFMPEG_BUILD}/bin/ffprobe" || return 1
  mkdir -p "$(media_tools_bin)"
  # One rename per binary, so a running agent never sees a half-written file.
  for tool in ffmpeg ffprobe; do
    chmod 775 "${work}/${VSS_FFMPEG_BUILD}/bin/${tool}"
    mv -f "${work}/${VSS_FFMPEG_BUILD}/bin/${tool}" "$(media_tools_bin)/${tool}"
  done
}

media_tools_install() {
  if media_tools_check >/dev/null; then
    echo "  ffmpeg and ffprobe already available ($(PATH="$(media_tools_path)" command -v ffmpeg))"
    return 0
  fi
  # The platform is overridable only so the hermetic tests can install a fake build on a laptop.
  local platform="${VSS_MEDIA_TOOLS_PLATFORM:-$(uname -s)-$(uname -m)}"
  if [ "${platform}" != "Linux-x86_64" ]; then
    echo "WARNING: no static ffmpeg build for ${platform}; install ffmpeg and ffprobe on PATH" >&2
    return 1
  fi

  local work status=0
  mkdir -p "${VSS_MEDIA_TOOLS_DIR}"
  work="$(mktemp -d "${VSS_MEDIA_TOOLS_DIR}/.install.XXXXXX")"
  _media_tools_fetch "${work}" || status=$?
  rm -rf "${work}"
  [ "${status}" -eq 0 ] || return "${status}"
  chmod g+rwx "${VSS_MEDIA_TOOLS_DIR}" "$(media_tools_bin)" 2>/dev/null || true
  media_tools_check
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  case "${1:-check}" in
    install) media_tools_install ;;
    check) media_tools_check ;;
    *)
      echo "Usage: $0 {install|check}" >&2
      exit 1
      ;;
  esac
fi
