#!/usr/bin/env bash
# Install a small daemon that mirrors any HDMI output connected to this
# kiosk onto its own panel (position 0,0), instead of cage's only two
# built-in modes: extend (splits the UI across both screens) or last
# (blanks every output but the newest). This kiosk only ever shows one
# fullscreen app, so extend is never useful if something ever gets plugged
# into the HDMI port — an HDMI capture card for documentation
# screenshots/recordings being the main reason to.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT=/opt/ha-kiosk

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends wlr-randr

install -d -m 755 "$INSTALL_ROOT/scripts"
install -m 755 "$ROOT/scripts/hdmi-mirror.sh" "$INSTALL_ROOT/scripts/hdmi-mirror.sh"
install -m 644 "$ROOT/scripts/ha-kiosk-hdmi-mirror.service" /etc/systemd/system/ha-kiosk-hdmi-mirror.service

systemctl daemon-reload
systemctl enable --now ha-kiosk-hdmi-mirror.service

echo "HDMI mirror daemon installed — anything plugged into HDMI now mirrors the panel instead of extending onto it."
