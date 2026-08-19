#!/usr/bin/env bash
# One-shot post-Debian-install setup: Wi-Fi firmware, kiosk, GPU stabilizers,
# sleep prevention, power drawer backend, charger fix, battery guard,
# thermal/power guardian, and camera.
# Usage: sudo bash scripts/install.sh ['http://homeassistant.local:8123/dashboard-kiosk']
# (URL is optional — omit it to get the on-tablet setup wizard on first boot.)
#
# Camera setup builds an out-of-tree kernel driver and needs network access.
# Skip it with: SKIP_CAMERA=1 sudo bash install.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0 ['http://homeassistant.local:8123/dashboard-kiosk']" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
HA_URL="${1:-}"
SKIP_CAMERA="${SKIP_CAMERA:-}"

echo "== 1/13: Wi-Fi firmware =="
bash "$ROOT/01-wifi-firmware.sh"

echo
echo "== 2/13: Kiosk install =="
bash "$ROOT/02-install-kiosk.sh" "$HA_URL"

echo
echo "== 3/13: GPU stabilizers =="
bash "$ROOT/03-fix-gpu.sh"

echo
echo "== 4/13: Sleep prevention =="
bash "$ROOT/06-no-sleep.sh"

echo
echo "== 5/13: Power drawer backend =="
bash "$ROOT/07-power-drawer.sh"

echo
echo "== 6/13: Charger fix =="
bash "$ROOT/10-fix-charger.sh"

echo
echo "== 7/13: Battery guard (clean shutdown at 1%) =="
bash "$ROOT/11-battery-guard.sh"

echo
echo "== 8/13: Guardian (low-battery dim, thermal camera cutoff) =="
bash "$ROOT/12-guardian.sh"

echo
echo "== 9/13: Shutdown reliability (bounded watchdog reset on hang) =="
bash "$ROOT/13-shutdown-reliability.sh"

echo
echo "== 10/13: Auto-rotate daemon (off by default — enable from Setup > General) =="
bash "$ROOT/14-auto-rotate.sh"

echo
echo "== 11/13: Self-update worker (check/apply updates from Setup > Updates) =="
bash "$ROOT/15-self-update.sh"

echo
if [[ -n "$SKIP_CAMERA" ]]; then
  echo "== 12/13: Camera — SKIPPED (SKIP_CAMERA set) =="
  echo "Run it later with: sudo bash $ROOT/09-install-camera.sh"
else
  echo "== 12/13: Camera =="
  echo "Building the kernel driver — needs network access, please wait."
  bash "$ROOT/09-install-camera.sh" || echo "WARNING: camera setup failed — the rest of the kiosk is unaffected. Re-run: sudo bash $ROOT/09-install-camera.sh"
fi

echo
echo "== 13/13: Done =="
echo "All done. Reboot to start the kiosk: sudo reboot"
