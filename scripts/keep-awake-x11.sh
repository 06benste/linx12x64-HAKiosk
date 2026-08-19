#!/bin/sh
# Keep the kiosk panel awake — unless an intentional blank is active.
# Flag is created by power-api display-off and cleared by display-on or touch-wake.
BLANK_FLAG="${BLANK_FLAG:-/opt/ha-kiosk/config/display_blanked}"

export DISPLAY="${DISPLAY:-:0}"
if [ -z "${XAUTHORITY:-}" ] && [ -f "$HOME/.Xauthority" ]; then
  export XAUTHORITY="$HOME/.Xauthority"
fi

xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true

while true; do
  if [ -f "$BLANK_FLAG" ]; then
    # Intentional blank: never run `xset -dpms` (that wakes the panel).
    # If the user touched the screen, DPMS reports Monitor is On — clear the flag.
    if xset q 2>/dev/null | grep -qi "Monitor is On"; then
      rm -f "$BLANK_FLAG"
      xset s off 2>/dev/null || true
      xset -dpms 2>/dev/null || true
      xset s noblank 2>/dev/null || true
    fi
  else
    xset s off 2>/dev/null || true
    xset -dpms 2>/dev/null || true
    xset s noblank 2>/dev/null || true
  fi
  sleep 5
done
