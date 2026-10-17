#!/usr/bin/env bash
#
# vm-preflight.sh — LAPTOP SIDE ONLY. Sourced by start.sh / tunnel.sh / tunnel-check.sh.
#
# Gives the VM side of start.sh clear failure reasons instead of a raw ssh error
# or an indefinite hang:
#   vm_preflight_ssh   probe SSH; on failure classify the cause (Tailscale not
#                      installed/stopped/logged out, VM offline in the tailnet,
#                      host does not resolve, timeout, refused, no route, auth,
#                      host key) and print the reason plus the next step.
#   vm_detect_ip       VM LAN address from its default route (VSS_VM_IP wins).
#
# Needs VSS_SSH_TARGET and VSS_SSH_HOST (see resolve-ssh-target.sh). Tests put a
# fake `ssh` / `tailscale` first on PATH (.scripts/test-vm-preflight.sh).

VSS_SSH_CONNECT_TIMEOUT="${VSS_SSH_CONNECT_TIMEOUT:-10}"
# Keep-alives turn a silently dead connection into an ssh exit instead of a hang.
VSS_SSH_OPTS=(-o BatchMode=yes -o "ConnectTimeout=${VSS_SSH_CONNECT_TIMEOUT}" -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

_vm_tailscale_bin() {
  if command -v tailscale >/dev/null 2>&1; then
    command -v tailscale
  elif [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]; then
    echo /Applications/Tailscale.app/Contents/MacOS/Tailscale
  fi
}

# Prints "state=<BackendState|none|daemon-down>" plus, when the VM is a tailnet
# peer, "peer_online=true|false" and "peer_lastseen=<ts>".
_vm_tailscale_facts() {
  local bin json host
  bin="$(_vm_tailscale_bin)"
  if [ -z "$bin" ]; then
    echo "state=none"
    return 0
  fi
  host="$(ssh -G "$VSS_SSH_HOST" 2>/dev/null | awk '/^hostname / {print $2}')"
  host="${host:-$VSS_SSH_HOST}"
  json="$("$bin" status --json 2>/dev/null || true)"
  printf '%s' "$json" | python3 -c '
import json, sys
host = sys.argv[1].split(".")[0].lower()
try:
    d = json.load(sys.stdin)
except Exception:
    print("state=daemon-down")
    sys.exit(0)
print("state=" + str(d.get("BackendState", "")))
for p in (d.get("Peer") or {}).values():
    names = {str(p.get("HostName", "")).lower(), str(p.get("DNSName", "")).split(".")[0].lower()}
    if host in names:
        print("peer_online=" + str(p.get("Online")).lower())
        print("peer_lastseen=" + str(p.get("LastSeen", "")))
' "$host" 2>/dev/null || echo "state=daemon-down"
}

# vm_explain_ssh_failure <ssh stderr>: print why the VM cannot be reached and what to do.
vm_explain_ssh_failure() {
  local err="$1" facts state peer_online peer_lastseen
  facts="$(_vm_tailscale_facts)"
  state="$(sed -n 's/^state=//p' <<<"$facts")"
  peer_online="$(sed -n 's/^peer_online=//p' <<<"$facts")"
  peer_lastseen="$(sed -n 's/^peer_lastseen=//p' <<<"$facts")"

  echo "start.sh: cannot reach the VM over SSH ('$VSS_SSH_TARGET')." >&2
  [ -n "$err" ] && echo "  SSH said: ${err}" >&2

  case "$state" in
    NeedsLogin|NeedsMachineAuth)
      echo "  Cause: Tailscale is not logged in on this laptop." >&2
      echo "  Fix:   run 'tailscale up' (or open the Tailscale app and sign in), then re-run start.sh." >&2
      return 0 ;;
    Stopped|NoState|Starting)
      echo "  Cause: Tailscale is installed but not running (state: ${state})." >&2
      echo "  Fix:   run 'tailscale up' (or switch Tailscale on in the menu bar), then re-run start.sh." >&2
      return 0 ;;
    daemon-down)
      echo "  Cause: the Tailscale daemon is not running (the CLI cannot talk to it)." >&2
      echo "  Fix:   open the Tailscale app (macOS) or run 'sudo systemctl start tailscaled' (Linux), then 'tailscale up'." >&2
      return 0 ;;
  esac
  if [ "$peer_online" = "false" ]; then
    echo "  Cause: Tailscale is up, but '$VSS_SSH_HOST' is OFFLINE in the tailnet (last seen: ${peer_lastseen:-unknown})." >&2
    echo "  Fix:   the VM is powered off or its tailscaled/network is down. Ask someone with access to kwanz-ws to power it on or run 'sudo systemctl restart tailscaled' there." >&2
    return 0
  fi

  case "$err" in
    *"Could not resolve hostname"*|*"Name or service not known"*|*"nodename nor servname"*)
      echo "  Cause: the host name '$VSS_SSH_HOST' does not resolve (DNS)." >&2
      if [ "$state" = "none" ]; then
        echo "  Note:  the Tailscale CLI was not found; if the host is a Tailscale name, install Tailscale and run 'tailscale up'." >&2
      fi
      echo "  Fix:   check the 'Host $VSS_SSH_HOST' entry (HostName) in ~/.ssh/config, that Tailscale MagicDNS is on, or set VSS_SSH_HOST to a resolvable name or IP." >&2 ;;
    *"timed out"*|*"Timeout"*|*"timeout"*)
      echo "  Cause: SSH timed out after ${VSS_SSH_CONNECT_TIMEOUT}s - nothing answered on port 22." >&2
      echo "  Fix:   the VM may be powered off, have no network path (Tailscale route/ACL), or a firewall drops SSH. Try 'tailscale ping $VSS_SSH_HOST'." >&2 ;;
    *"Connection refused"*)
      echo "  Cause: the VM is reachable but its SSH server is not running (connection refused on port 22)." >&2
      echo "  Fix:   start it from the VM console: 'sudo systemctl start ssh' (or 'sshd'). Nothing can be started from the laptop until SSH is back." >&2 ;;
    *"No route to host"*|*"Network is unreachable"*)
      echo "  Cause: this laptop has no network route to the VM address." >&2
      echo "  Fix:   check Wi-Fi/VPN and Tailscale ('tailscale status'), then re-run." >&2 ;;
    *"REMOTE HOST IDENTIFICATION HAS CHANGED"*|*"Host key verification failed"*)
      echo "  Cause: the VM's SSH host key changed (reinstall or new machine behind the name)." >&2
      echo "  Fix:   if that is expected, run 'ssh-keygen -R $VSS_SSH_HOST', then 'ssh $VSS_SSH_TARGET' once to accept the new key." >&2 ;;
    *"Permission denied"*|*"Too many authentication failures"*)
      echo "  Cause: the VM answered but rejected the login for '$VSS_SSH_TARGET' (no accepted key)." >&2
      echo "  Fix:   check the username (VSS_SSH_USER / VSS_SSH_TARGET), that your key is loaded ('ssh-add -l') and authorised on the VM." >&2 ;;
    *"Connection closed"*|*"Connection reset"*|*"kex_exchange_identification"*)
      echo "  Cause: the VM accepted the connection then dropped it (sshd overloaded, restarting or blocking this client)." >&2
      echo "  Fix:   wait a minute and re-run; if it persists, check 'journalctl -u ssh' on the VM." >&2 ;;
    *)
      echo "  Cause: unclassified SSH failure." >&2
      echo "  Fix:   run 'ssh -v $VSS_SSH_TARGET true' to see the handshake, and check 'tailscale status'." >&2 ;;
  esac
  return 0
}

# vm_preflight_ssh: returns 0 if the VM answers over SSH, otherwise explains and returns 1.
vm_preflight_ssh() {
  local err
  if err="$(ssh "${VSS_SSH_OPTS[@]}" "$VSS_SSH_TARGET" true 2>&1)"; then
    return 0
  fi
  # One retry: a Tailscale relay path can time out once while it re-establishes.
  case "$err" in *"timed out"*|*"Connection closed"*|*"Connection reset"*)
    sleep 2
    if err="$(ssh "${VSS_SSH_OPTS[@]}" "$VSS_SSH_TARGET" true 2>&1)"; then
      return 0
    fi ;;
  esac
  vm_explain_ssh_failure "$err"
  return 1
}

# vm_detect_ip: print the VM address to forward the tunnel to. An explicit
# VSS_VM_IP wins; otherwise the default-route source address read over SSH, else
# the historical 10.131.1.5 (with a note on stderr).
vm_detect_ip() {
  local ip
  if [ -n "${VSS_VM_IP:-}" ]; then
    echo "$VSS_VM_IP"
    return 0
  fi
  ip="$(ssh "${VSS_SSH_OPTS[@]}" "$VSS_SSH_TARGET" 'ip -4 route get 1.1.1.1' 2>/dev/null \
    | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n 1 || true)"
  if [ -n "$ip" ]; then
    echo "start.sh: detected VM address $ip (set VSS_VM_IP to override)." >&2
    echo "$ip"
  else
    echo "start.sh: could not detect the VM address; falling back to 10.131.1.5 (set VSS_VM_IP to override)." >&2
    echo "10.131.1.5"
  fi
}

# vm_ssh_limited <seconds> <ssh args...>: run ssh (stdin passed through) with a hard
# laptop-side limit, so a stuck remote step ends in a message instead of a hang. It
# runs ssh in the background and waits, so Ctrl-C reaches start.sh's trap (a
# foreground ssh child swallows it). Exit 143 means the limit was hit or ssh was killed.
VM_SSH_PID=""
vm_ssh_limited() {
  local limit="$1" rc=0 watchdog
  shift
  # shellcheck disable=SC2029
  ssh "${VSS_SSH_OPTS[@]}" "$@" <&0 &
  VM_SSH_PID=$!
  {
    sleep "$limit" &
    local sleeper=$!
    trap 'kill "$sleeper" 2>/dev/null; exit 0' TERM
    wait "$sleeper" && kill "$VM_SSH_PID" 2>/dev/null
  } >/dev/null 2>&1 &
  watchdog=$!
  wait "$VM_SSH_PID" || rc=$?
  kill "$watchdog" 2>/dev/null || true
  wait "$watchdog" 2>/dev/null || true
  VM_SSH_PID=""
  return "$rc"
}
