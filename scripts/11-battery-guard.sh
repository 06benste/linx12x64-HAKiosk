#!/usr/bin/env bash
# Install the low-battery clean-shutdown guard: watches the fuel gauge and
# runs `systemctl poweroff` if capacity hits 1% while unplugged, instead of
# letting the hardware hard-cut uncleanly.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT=/opt/ha-kiosk

install -d -m 755 "$INSTALL_ROOT/scripts"
install -m 755 "$ROOT/scripts/battery-guard.py" "$INSTALL_ROOT/scripts/battery-guard.py"
install -m 644 "$ROOT/scripts/ha-kiosk-battery-guard.service" /etc/systemd/system/ha-kiosk-battery-guard.service

systemctl daemon-reload
systemctl enable --now ha-kiosk-battery-guard.service

echo "Battery guard installed."
systemctl status ha-kiosk-battery-guard.service --no-pager -l | head -10 || true
