#!/usr/bin/env bash
# Bounds the worst-case shutdown/reboot hang. If the AtomISP camera driver
# ever wedges a capture process into an uninterruptible D-state (kernel bug,
# not something any signal can fix — see camera-stream-server.py's
# _graceful_pkill for the mitigation on the app side), systemd-shutdown just
# waits for it to exit, which it never will. The only backstop is this
# tablet's hardware watchdog (wdat_wdt) — but systemd's default
# RebootWatchdogSec is 10 minutes, which is a very long time for an
# unattended kiosk to sit there mid-shutdown. Shortening it means a genuine
# wedge still recovers in under two minutes instead.
set -euo pipefail

CONF=/etc/systemd/system.conf
VALUE="RebootWatchdogSec=90s"

if grep -q '^RebootWatchdogSec=' "$CONF"; then
  sed -i "s/^RebootWatchdogSec=.*/$VALUE/" "$CONF"
elif grep -q '^#RebootWatchdogSec=' "$CONF"; then
  sed -i "s/^#RebootWatchdogSec=.*/$VALUE/" "$CONF"
else
  echo "$VALUE" >>"$CONF"
fi

# Re-exec PID 1 in place so the new watchdog setting is live immediately,
# without needing a reboot to pick it up.
systemctl daemon-reexec

echo "RebootWatchdogSec set to 90s (hardware default was 10min)"
