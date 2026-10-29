#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Run a command while the Windows host is asked to stay awake (WSL only), then release the request.
#
#   experiments/keep-awake.sh -- .venv/bin/python scripts/eval_experiment.py run <configs> --confirm-paid
#
# Stage 1 lost its last 12 calls to a Modern Standby entered on a lid close (2026-10-28 12:51 SGT) that lasted
# about 4 h on battery. This wrapper holds SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) in a
# PowerShell process for the command's lifetime, which prevents idle sleep. It cannot override closing the lid
# or a power-button press: keep the laptop open and on AC power. The runner still detects any suspend
# (host_suspended). Changes no power setting; outside WSL it just runs the command.
set -euo pipefail

[ "${1:-}" = "--" ] && shift
[ $# -gt 0 ] || { echo "usage: $0 -- <command> [args...]" >&2; exit 2; }

if ! grep -qi microsoft /proc/version 2>/dev/null || ! command -v powershell.exe >/dev/null; then
  echo "keep-awake: not WSL with powershell.exe; running without a wake request" >&2
  exec "$@"  # outside WSL the runner does not require KEEP_AWAKE_ACTIVE
fi

ps_script=$(cat <<'PS'
Add-Type -Namespace KeepAwake -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
if ([KeepAwake.Power]::SetThreadExecutionState([uint32]"0x80000001") -eq 0) { Write-Host "keep-awake: wake request FAILED"; exit 1 }
Write-Host "keep-awake: wake request held"
while ($null -ne [Console]::In.ReadLine()) { }
$null = [KeepAwake.Power]::SetThreadExecutionState([uint32]"0x80000000")
Write-Host "keep-awake: wake request released"
PS
)
# PowerShell reads stdin until this script exits and closes fd 3, then releases the request and ends.
exec 3> >(powershell.exe -NoProfile -NonInteractive -Command "$ps_script" >&2)
KEEP_AWAKE_ACTIVE=1 "$@"
