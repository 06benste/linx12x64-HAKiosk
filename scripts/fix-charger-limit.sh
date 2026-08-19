#!/bin/bash
# Raise AXP288 USB input current limit.
# Cherry Trail tablets often enumerate the wall wart as SDP @ 500mA while the
# kiosk draws ~1A, so the battery discharges while "plugged in" and the unit
# hard-cuts (journal ends uncleanly; last -x shows "crash").
set -euo pipefail
P=/sys/class/power_supply/axp288_charger/input_current_limit
[ -f "$P" ] || exit 0
for v in 2000000 1500000 900000; do
  if echo "$v" > "$P" 2>/dev/null; then
    logger -t ha-kiosk-charger "set input_current_limit=$v"
    exit 0
  fi
done
logger -t ha-kiosk-charger "failed to raise input_current_limit"
exit 1
