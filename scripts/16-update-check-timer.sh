#!/usr/bin/env bash
# Install a daily (06:00, +/- 5min jitter) background check for both
# kiosk-software and Debian package updates, so the power drawer's tab can
# show a notification bubble without anyone needing to open Setup > Updates
# and tap Check. self-update.py's check/os-check subcommands already write
# their result into update-available.json themselves (power-api.py's
# /update-available reads it back) — this just runs them on a schedule.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

install -m 644 "$ROOT/scripts/ha-kiosk-update-check.service" /etc/systemd/system/ha-kiosk-update-check.service
install -m 644 "$ROOT/scripts/ha-kiosk-update-check.timer" /etc/systemd/system/ha-kiosk-update-check.timer

systemctl daemon-reload
systemctl enable --now ha-kiosk-update-check.timer

echo "Daily update-check timer installed (06:00 +/- 5min)."
systemctl list-timers ha-kiosk-update-check.timer --no-pager || true
