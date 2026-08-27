#!/usr/bin/env bash
# Bounds the worst-case shutdown/reboot hang: if the AtomISP driver wedges
# a capture process into an uninterruptible D-state (a kernel bug no signal
# can fix — see camera-stream-server.py's _graceful_pkill for the app-side
# mitigation), systemd-shutdown waits forever for it to exit. The hardware
# watchdog is the only backstop, but its default 10-minute timeout is too
# long for an unattended kiosk; 90s means a genuine wedge recovers quickly.
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

# Re-exec PID 1 so the new setting is live without a reboot.
systemctl daemon-reexec

echo "RebootWatchdogSec set to 90s (hardware default was 10min)"
