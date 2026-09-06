#!/bin/bash
#
# Drishti Workbench — air-gap lockdown (macOS)
#
# Blocks all outbound network traffic except loopback and private/Docker
# networks, using pf (the macOS packet filter). Linux guides reach for
# iptables; macOS does not have it, and pf is the supported equivalent.
#
# This turns the sovereignty claim into something a sceptic can test on stage:
# with these rules loaded, `curl https://google.com` fails while Drishti keeps
# working, because every dependency it has is on this machine.
#
# ---------------------------------------------------------------------------
# WARNING — this cuts this Mac off from the internet for every application,
# not just Drishti. Your browser, Slack, and any SSH session over the public
# internet will stop working until you run scripts/airgap_unlock.sh.
#
# Use --duration to schedule an automatic unlock, which is strongly advised if
# you are running this over a remote connection you could lock yourself out of.
# ---------------------------------------------------------------------------
#
# Usage:
#   sudo ./scripts/airgap_lockdown.sh                 # until manually unlocked
#   sudo ./scripts/airgap_lockdown.sh --duration 300  # auto-unlock after 5 min

set -euo pipefail

RULES_FILE="/var/tmp/drishti-airgap.conf"
STATE_FILE="/var/tmp/drishti-airgap.state"
DURATION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration|-d) DURATION="${2:-}"; shift 2 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

if [[ "$(id -u)" -ne 0 ]]; then
    echo "This script must run as root (pf requires it):" >&2
    echo "  sudo $0 $*" >&2
    exit 1
fi

# Cancel any auto-unlock left over from a previous run. Without this, an
# earlier --duration timer keeps counting and will lift the lockdown partway
# through this one — silently, and most likely mid-demo.
if [[ -f "$STATE_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$STATE_FILE"
    if [[ -n "${unlock_pid:-}" ]] && kill -0 "$unlock_pid" 2>/dev/null; then
        kill "$unlock_pid" 2>/dev/null && \
            echo "Cancelled a pending auto-unlock from an earlier run (pid $unlock_pid)."
    fi
    unset unlock_pid
fi

# Remember whether pf was already enabled, so the unlock script restores the
# machine to the state it was actually in rather than a guess at it.
if pfctl -s info 2>/dev/null | head -1 | grep -q "Enabled"; then
    echo "pf_was_enabled=1" > "$STATE_FILE"
else
    echo "pf_was_enabled=0" > "$STATE_FILE"
fi

cat > "$RULES_FILE" <<'RULES'
#
# Drishti air-gap ruleset.
#
# pf evaluates every rule in order and the LAST match wins — unless a rule is
# marked "quick", which makes it match immediately and stop evaluation. So the
# shape below is: one broad block, then specific "quick" exceptions that
# override it.
#

# Skip filtering entirely on the loopback interface. The frontend talks to the
# backend, and the backend talks to Ollama and ChromaDB, all over 127.0.0.1 —
# this is the traffic the app actually needs, and it never leaves the machine.
set skip on lo0

# Default deny for anything leaving this host. Everything after this line is
# an explicitly justified exception.
block drop out all

# --- Exceptions, all "quick" so they beat the block above -------------------

# Loopback by address as well as by interface. Belt and braces: some tools
# bind to 127.0.0.1 on an interface other than lo0.
pass out quick inet from any to 127.0.0.0/8

# RFC 1918 private ranges. Three reasons these are allowed:
#   10.0.0.0/8      — plant LAN, so other machines in the refinery can reach
#                     the workbench, and so it can reach an on-prem GPU server
#                     running vLLM later.
#   172.16.0.0/12   — Docker's default bridge networks. The compose stack talks
#                     backend <-> ollama over this.
#   192.168.0.0/16  — typical LAN, and Docker Desktop's own 192.168.65.0/24.
#
# Allowing these does NOT leak to the internet. pf matches on the destination
# address in the IP header, not on the next hop, so a packet addressed to a
# public IP is still dropped even though the router that would forward it sits
# inside one of these ranges.
pass out quick inet from any to 10.0.0.0/8
pass out quick inet from any to 172.16.0.0/12
pass out quick inet from any to 192.168.0.0/16

# Link-local (169.254/16). Used by some virtualisation interfaces.
pass out quick inet from any to 169.254.0.0/16

# The IPv6 equivalents: loopback, unique-local, link-local. Without these an
# IPv6-preferring resolver can slip past the IPv4 rules above.
pass out quick inet6 from any to ::1
pass out quick inet6 from any to fc00::/7
pass out quick inet6 from any to fe80::/10
RULES

echo "Loading air-gap ruleset…"
# -f replaces the active ruleset. The previous one is restored from
# /etc/pf.conf by the unlock script.
pfctl -f "$RULES_FILE" 2>&1 | grep -v "^No ALTQ support" || true
pfctl -e 2>&1 | grep -v "^No ALTQ support" || true

echo
echo "🔒 AIR-GAP ACTIVE"
echo "   Allowed : loopback, 10/8, 172.16/12, 192.168/16, 169.254/16, IPv6 local"
echo "   Blocked : everything else outbound"
echo
echo "   Verify : curl -m 5 https://google.com     (should fail)"
echo "            curl http://localhost:8000/health (should succeed)"
echo "   Unlock : sudo ./scripts/airgap_unlock.sh"

if [[ -n "$DURATION" ]]; then
    UNLOCK="$(cd "$(dirname "$0")" && pwd)/airgap_unlock.sh"
    # Detached so it survives this shell exiting. This is the dead-man's
    # switch: even if the terminal is closed or the demo machine is left
    # alone, connectivity comes back on its own.
    nohup bash -c "sleep $DURATION; '$UNLOCK'" >/dev/null 2>&1 &
    # Recorded so an early manual unlock can cancel it, and so the next
    # lockdown does not inherit it.
    echo "unlock_pid=$!" >> "$STATE_FILE"
    echo
    echo "   ⏱  Auto-unlock scheduled in ${DURATION}s (pid $!)"
fi
