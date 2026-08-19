#!/usr/bin/env bash
# Install the secondary power/thermal guardian: dims the display when
# battery is low and discharging, and turns the camera off if CPU/SoC temp
# stays elevated for a while. Separate from 11-battery-guard.sh's critical
# shutdown-at-1% daemon, which stays dependency-free on purpose — this one
# calls power-api.py, so its worst failure mode is "didn't mitigate",
# never "missed a critical shutdown".
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT=/opt/ha-kiosk

install -d -m 755 "$INSTALL_ROOT/scripts"
install -m 755 "$ROOT/scripts/kiosk-guardian.py" "$INSTALL_ROOT/scripts/kiosk-guardian.py"
install -m 644 "$ROOT/scripts/ha-kiosk-guardian.service" /etc/systemd/system/ha-kiosk-guardian.service

systemctl daemon-reload
systemctl enable --now ha-kiosk-guardian.service

echo "Guardian installed."
systemctl status ha-kiosk-guardian.service --no-pager -l | head -10 || true
