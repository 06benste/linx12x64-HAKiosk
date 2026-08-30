#!/usr/bin/env bash
# One-shot post-Debian-install setup: Wi-Fi firmware, kiosk, GPU stabilizers,
# sleep prevention, power drawer backend, charger fix, background daemons
# (battery guard, guardian, auto-rotate, self-update, HDMI mirror), bounded
# shutdown watchdog, and camera.
# Usage (as root — run 'su -' first): bash scripts/install.sh ['http://homeassistant.local:8123/dashboard-kiosk']
# (URL is optional — omit it to get the on-tablet setup wizard on first boot.)
#
# Camera setup builds an out-of-tree kernel driver and needs network access.
# Skip it with: SKIP_CAMERA=1 bash install.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root — run 'su -' first, then: bash $0 ['http://homeassistant.local:8123/dashboard-kiosk']" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
HA_URL="${1:-}"
SKIP_CAMERA="${SKIP_CAMERA:-}"

echo "== 1/10: Wi-Fi firmware =="
bash "$ROOT/01-wifi-firmware.sh"

echo
echo "== 2/10: Kiosk install =="
bash "$ROOT/02-install-kiosk.sh" "$HA_URL"

echo
echo "== 3/10: GPU stabilizers =="
bash "$ROOT/03-fix-gpu.sh"

echo
echo "== 4/10: Sleep prevention =="
bash "$ROOT/06-no-sleep.sh"

echo
echo "== 5/10: Power drawer backend =="
bash "$ROOT/07-power-drawer.sh"

echo
echo "== 6/10: Charger fix =="
bash "$ROOT/10-fix-charger.sh"

echo
echo "== 7/10: Background daemons (battery guard, guardian, auto-rotate, self-update, HDMI mirror) =="
bash "$ROOT/11-daemons.sh"

echo
echo "== 8/10: Shutdown reliability (bounded watchdog reset on hang) =="
bash "$ROOT/12-shutdown-reliability.sh"

echo
if [[ -n "$SKIP_CAMERA" ]]; then
  echo "== 9/10: Camera — SKIPPED (SKIP_CAMERA set) =="
  echo "Run it later with: su -c 'bash $ROOT/09-install-camera.sh'"
else
  echo "== 9/10: Camera =="
  echo "Building the kernel driver — needs network access, please wait."
  bash "$ROOT/09-install-camera.sh" || echo "WARNING: camera setup failed — the rest of the kiosk is unaffected. Re-run: su -c 'bash $ROOT/09-install-camera.sh'"
fi

echo
echo "== 10/10: Done =="
echo "All done. Reboot to start the kiosk: reboot"
