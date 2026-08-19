#!/usr/bin/env bash
# Install the accelerometer-driven auto-rotate daemon (scripts/auto-rotate.py):
# watches the onboard IIO accelerometer and calls power-api's /rotate when the
# tablet's physical orientation changes. Disabled by default here — enabling
# it is a General-tab toggle in the setup page (power-api's /auto-rotate),
# same as camera power and the charge LED.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT=/opt/ha-kiosk

install -d -m 755 "$INSTALL_ROOT/scripts"
install -m 755 "$ROOT/scripts/auto-rotate.py" "$INSTALL_ROOT/scripts/auto-rotate.py"
install -m 644 "$ROOT/scripts/ha-kiosk-auto-rotate.service" /etc/systemd/system/ha-kiosk-auto-rotate.service

systemctl daemon-reload
# Not enabled/started here — off by default until turned on from the setup
# page's General tab (mirrors camera power / charge LED's own default-off
# install-time state, decided by the user rather than assumed).

echo "Auto-rotate daemon installed (off by default — enable it from the tablet's Setup > General tab)."
