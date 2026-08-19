#!/usr/bin/env bash
# Raise the AXP288 charger's USB input current limit, persistently.
#
# Cherry Trail tablets often enumerate the wall wart as SDP @ 500mA while the
# kiosk draws ~1A, so the battery slowly discharges even while "plugged in"
# and the tablet hard-cuts overnight. This applies the fix now, installs it
# as a boot-time service, and re-applies it via udev whenever the charger
# device reappears (e.g. unplug/replug).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT="/opt/ha-kiosk"

P=/sys/class/power_supply/axp288_charger/input_current_limit
B=/sys/class/power_supply/axp288_fuel_gauge

if [[ -f "$P" ]]; then
  for v in 2000000 2400000 1500000; do
    if echo "$v" > "$P" 2>/dev/null; then
      echo "live set $v"
      break
    fi
  done
  echo "icl now $(cat "$P")"
else
  echo "No AXP288 charger sysfs node — nothing to fix on this hardware."
fi
if [[ -d "$B" ]]; then
  sleep 3
  echo "status=$(cat "$B/status") cap=$(cat "$B/capacity") I=$(cat "$B/current_now") V=$(cat "$B/voltage_now")"
fi

install -d -m 755 "$INSTALL_ROOT/scripts"
install -m 755 "$ROOT/scripts/fix-charger-limit.sh" "$INSTALL_ROOT/scripts/fix-charger-limit.sh"
install -m 644 "$ROOT/scripts/ha-kiosk-charger-limit.service" /etc/systemd/system/ha-kiosk-charger-limit.service
install -m 644 "$ROOT/scripts/99-ha-kiosk-axp288-charge.rules" /etc/udev/rules.d/99-ha-kiosk-axp288-charge.rules

systemctl daemon-reload
systemctl enable --now ha-kiosk-charger-limit.service
udevadm control --reload

sleep 2
echo "--- verify ---"
systemctl status ha-kiosk-charger-limit.service --no-pager -l | head -20 || true
if [[ -f "$P" ]]; then
  echo "icl=$(cat "$P")"
fi
if [[ -d "$B" ]]; then
  echo "status=$(cat "$B/status") I=$(cat "$B/current_now") cap=$(cat "$B/capacity")"
fi
echo "Charger fix installed."
