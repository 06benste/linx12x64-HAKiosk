#!/usr/bin/env bash
# Installs every small background daemon this kiosk runs: battery guard
# (clean shutdown at 1%), guardian (low-battery dim / thermal camera
# cutoff), auto-rotate (off by default — enabled from Setup > General),
# the self-update worker, its daily 06:00 update-check timer, and the
# HDMI-mirror daemon. One script instead of six near-identical ones — each
# is still just "install a script + a systemd unit, enable it".
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT=/opt/ha-kiosk
install -d -m 755 "$INSTALL_ROOT/scripts" "$INSTALL_ROOT/logs"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends curl ca-certificates wlr-randr

# Battery guard — shuts down cleanly at 1% instead of a hard cut
install -m 755 "$ROOT/scripts/battery-guard.py" "$INSTALL_ROOT/scripts/battery-guard.py"
install -m 644 "$ROOT/scripts/ha-kiosk-battery-guard.service" /etc/systemd/system/ha-kiosk-battery-guard.service

# Guardian — dims on low battery, cuts the camera if it runs hot
install -m 755 "$ROOT/scripts/kiosk-guardian.py" "$INSTALL_ROOT/scripts/kiosk-guardian.py"
install -m 644 "$ROOT/scripts/ha-kiosk-guardian.service" /etc/systemd/system/ha-kiosk-guardian.service

# Auto-rotate — installed but left off; Setup > General turns it on
install -m 755 "$ROOT/scripts/auto-rotate.py" "$INSTALL_ROOT/scripts/auto-rotate.py"
install -m 644 "$ROOT/scripts/ha-kiosk-auto-rotate.service" /etc/systemd/system/ha-kiosk-auto-rotate.service

# Self-update worker — pulls new releases / applies Debian upgrades from
# Setup > Updates. Only writes a version marker if one doesn't already
# exist — a successful self-update always overwrites it with the real
# applied tag, so this is purely the first-ever-run fallback.
install -m 755 "$ROOT/scripts/self-update.py" "$INSTALL_ROOT/scripts/self-update.py"
if [[ ! -f "$INSTALL_ROOT/version" && -f "$ROOT/VERSION" ]]; then
  install -m 644 "$ROOT/VERSION" "$INSTALL_ROOT/version"
fi

# Daily update-check timer — feeds the power drawer's notification bubble
install -m 644 "$ROOT/scripts/ha-kiosk-update-check.service" /etc/systemd/system/ha-kiosk-update-check.service
install -m 644 "$ROOT/scripts/ha-kiosk-update-check.timer" /etc/systemd/system/ha-kiosk-update-check.timer

# HDMI mirror — mirrors instead of extending onto a connected output
install -m 755 "$ROOT/scripts/hdmi-mirror.sh" "$INSTALL_ROOT/scripts/hdmi-mirror.sh"
install -m 644 "$ROOT/scripts/ha-kiosk-hdmi-mirror.service" /etc/systemd/system/ha-kiosk-hdmi-mirror.service

systemctl daemon-reload
systemctl enable --now \
  ha-kiosk-battery-guard.service \
  ha-kiosk-guardian.service \
  ha-kiosk-update-check.timer \
  ha-kiosk-hdmi-mirror.service

echo "Daemons installed: battery guard, guardian, auto-rotate (off by default), self-update, daily update-check, HDMI mirror."
