#!/bin/bash
# Wrapper: grade with the same PIL path the tuner GUI uses.
set -euo pipefail
OUT="${1:-/tmp/ha-kiosk-camera.jpg}"
exec python3 /opt/ha-kiosk/scripts/capture-tablet-cam.py "$OUT"
