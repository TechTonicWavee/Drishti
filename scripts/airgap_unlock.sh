#!/bin/bash
#
# Drishti Workbench — reverse the air-gap lockdown (macOS)
#
# Restores the machine to normal development networking by reloading the
# system's own pf configuration and putting pf back into the enabled or
# disabled state it was in before the lockdown ran.
#
# Usage:
#   sudo ./scripts/airgap_unlock.sh

set -euo pipefail

RULES_FILE="/var/tmp/drishti-airgap.conf"
STATE_FILE="/var/tmp/drishti-airgap.state"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "This script must run as root (pf requires it):" >&2
    echo "  sudo $0" >&2
    exit 1
fi

# Reload the stock macOS ruleset, replacing ours.
if [[ -f /etc/pf.conf ]]; then
    pfctl -f /etc/pf.conf 2>&1 | grep -v "^No ALTQ support" || true
fi

# pf is disabled by default on macOS. Only leave it enabled if it already was
# before the lockdown, so we neither strand the machine behind a filter it did
# not have nor switch off one it did.
PF_WAS_ENABLED=0
# shellcheck disable=SC1090
[[ -f "$STATE_FILE" ]] && source "$STATE_FILE"

if [[ "${pf_was_enabled:-0}" -eq 1 ]]; then
    pfctl -e 2>&1 | grep -v "^No ALTQ support" || true
    echo "pf left enabled with the system ruleset (it was enabled beforehand)."
else
    pfctl -d 2>&1 | grep -v "^No ALTQ support" || true
    echo "pf disabled (it was disabled beforehand)."
fi

rm -f "$RULES_FILE" "$STATE_FILE"

echo
echo "🔓 AIR-GAP LIFTED — normal network access restored."
echo "   Verify : curl -m 5 -o /dev/null -s -w '%{http_code}\n' https://google.com"
