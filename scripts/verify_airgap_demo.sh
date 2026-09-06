#!/bin/bash
#
# Drishti Workbench — one-command air-gap verification.
#
# Engages the lockdown, proves the public internet is gone, runs all three
# demo flows against the local stack, checks the outbound counter never left
# zero, and lifts the lockdown again.
#
# This exists because proving `curl` fails is only half the claim. The half
# that matters is that everything still works while it fails.
#
# Usage:
#   sudo ./scripts/verify_airgap_demo.sh
#
# Start the backend first; the frontend is not needed for this check.

# Deliberately not `set -e`. A failing step must still reach the unlock at the
# end — leaving the machine cut off because a test failed would be worse than
# the failure.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API=http://127.0.0.1:8000
PY="$ROOT/backend/.venv/bin/python"
SCAN="$ROOT/backend/data/sample_docs/scanned/vessel_v204_inspection.png"
FAILURES=0

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Must run as root (pf requires it):  sudo $0" >&2
    exit 1
fi

if ! curl -sf --max-time 5 "$API/health" >/dev/null; then
    echo "Backend is not answering on $API — start it first." >&2
    exit 1
fi

# Whatever happens below, the lockdown comes off. This trap is the safety net:
# an unexpected error must not leave the machine offline.
cleanup() {
    echo
    echo "── Lifting the lockdown"
    "$ROOT/scripts/airgap_unlock.sh"
}
trap cleanup EXIT

counter() {
    curl -s --max-time 5 "$API/system/network-status" \
        | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print(d["external_call_attempts"], d["internal_call_count"])'
}

check() {  # check <label> <expected> <actual>
    if [[ "$2" == "$3" ]]; then
        echo "   ✅ $1"
    else
        echo "   ❌ $1  (expected $2, got $3)"
        FAILURES=$((FAILURES + 1))
    fi
}

read -r EXT_BEFORE INT_BEFORE <<<"$(counter)"
echo "Counter before:  external=$EXT_BEFORE  internal=$INT_BEFORE"

echo
echo "── Engaging the lockdown (auto-unlock in 900s as a backstop)"
"$ROOT/scripts/airgap_lockdown.sh" --duration 900 >/dev/null || {
    echo "Lockdown failed to load." >&2; exit 1; }
echo "   pf ruleset loaded"

echo
echo "── The public internet should now be gone"
if curl -s --max-time 6 -o /dev/null https://google.com; then
    echo "   ❌ google.com was still reachable — the lockdown did not take"
    FAILURES=$((FAILURES + 1))
else
    echo "   ✅ https://google.com unreachable"
fi
if curl -sf --max-time 5 "$API/health" >/dev/null; then
    echo "   ✅ the workbench is still up"
else
    echo "   ❌ the workbench went down with the network"
    FAILURES=$((FAILURES + 1))
fi

flow() {  # flow <label> <expected agent> <curl args...>
    local label="$1" expect="$2"; shift 2
    local start elapsed agent
    start=$(date +%s)
    agent=$(curl -sN --max-time 600 "$@" | "$PY" -c '
import sys, json
lines = sys.stdin.read().split("\n")
for i, l in enumerate(lines):
    if l.startswith("event: routing"):
        print(json.loads(lines[i + 1][5:])["agent"]); break
else:
    print("(no routing frame)")
')
    elapsed=$(( $(date +%s) - start ))
    echo "   $label — ${elapsed}s"
    check "     routed to $expect" "$expect" "$agent"
}

echo
echo "── Walking the three demo flows, fully offline"
flow "Flow A (RAG)" "Reasoning Agent" \
    -X POST "$API/chat" -H 'Content-Type: application/json' \
    -d '{"message":"What is the shutdown procedure for the FCC unit?"}'
flow "Flow B (sandbox)" "Coder Agent" \
    -X POST "$API/chat" -H 'Content-Type: application/json' \
    -d '{"message":"Write a python script that prints the first 10 fibonacci numbers."}'
flow "Flow C (scan to docx)" "Vision Agent" \
    -X POST "$API/chat/upload" -F "file=@$SCAN" \
    -F "message=Draft an approval note from this."

echo
echo "── Counters and sockets"
read -r EXT_AFTER INT_AFTER <<<"$(counter)"
check "external call attempts still zero" "0" "$EXT_AFTER"
if [[ "$INT_AFTER" -gt "$INT_BEFORE" ]]; then
    echo "   ✅ internal calls rose $INT_BEFORE → $INT_AFTER (the counter is live)"
else
    echo "   ❌ internal counter did not move — is it actually recording?"
    FAILURES=$((FAILURES + 1))
fi
"$PY" "$ROOT/backend/scripts/traffic_monitor.py" --once | tail -4

echo
if [[ "$FAILURES" -eq 0 ]]; then
    echo "════ ALL CHECKS PASSED — three flows ran with no route to the internet ════"
else
    echo "════ $FAILURES CHECK(S) FAILED ════"
fi
exit "$FAILURES"
