#!/bin/sh
# cage only ever shows one thing: this kiosk's single fullscreen Chromium
# app. Its default "extend" output mode (the only alternative built in is
# "last", which blanks every output but the newest) is never what you'd
# want here — there's nothing to spread across two screens. cage has no
# built-in mirror mode (see cage-kiosk/cage#453, open/unimplemented as of
# cage 0.3), so this reproduces one: outputs that occupy the same
# rectangle in cage's layout both render the same content, so repositioning
# any newly-connected output onto the panel's own origin (0,0) via the
# wlr-output-management protocol (wlr-randr) mirrors it.
#
# Runs as a poll loop rather than a udev hotplug rule — simpler to get
# right than reliably matching DRM "change" events, and cheap enough (one
# wlr-randr call every few seconds) not to matter on this hardware.
#
# eDP-1 is this exact tablet model's panel name (confirmed via wlr-randr on
# device) — hardcoded like the rest of this project's hardware-specific
# scripts, not meant to be portable to other hardware.
PRIMARY="${HDMI_MIRROR_PRIMARY:-eDP-1}"

RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export XDG_RUNTIME_DIR="$RUNTIME_DIR"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

while true; do
  wlr-randr 2>/dev/null | awk -v primary="$PRIMARY" '
    /^[A-Za-z]/ { name = $1 }
    /Position:/ { if (name != primary && name != "") print name, $2 }
  ' | while read -r name pos; do
    if [ "$pos" != "0,0" ]; then
      wlr-randr --output "$name" --pos 0,0 2>/dev/null || true
    fi
  done
  sleep 5
done
