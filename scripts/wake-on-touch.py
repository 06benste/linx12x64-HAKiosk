#!/usr/bin/env python3
"""Wake the panel on any input activity while intentionally blanked.

Backlight-based blanking (power-api.py's set_display_blanked, using
bl_power) has no built-in "any touch wakes the screen" behavior the way X11
DPMS did — a DPMS-blanked X11 display auto-wakes on any input event at the
X server level; a raw bl_power sysfs write has no equivalent hook, and
nothing else was watching for input to reverse it. This polls every
/dev/input/event* device and, on activity while the intentional-blank flag
is set, calls the power API's display-on action.
"""
from __future__ import annotations

import glob
import os
import select
import time
import urllib.request

BLANK_FLAG = "/opt/ha-kiosk/config/display_blanked"
POWER_API = "http://127.0.0.1:17823/display-on"
RESCAN_EVERY_S = 30.0


def open_devices() -> dict[int, str]:
    fds: dict[int, str] = {}
    for path in glob.glob("/dev/input/event*"):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            fds[fd] = path
        except OSError:
            continue
    return fds


def wake() -> None:
    req = urllib.request.Request(
        POWER_API, method="POST", data=b"{}", headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:  # noqa: BLE001
        print(f"wake request failed: {exc}", flush=True)


def main() -> None:
    fds = open_devices()
    print(f"watching {len(fds)} input devices for wake-on-touch", flush=True)
    last_rescan = time.monotonic()

    while True:
        try:
            readable, _, _ = select.select(list(fds.keys()), [], [], 5.0)
        except OSError:
            readable = []

        if readable:
            for fd in readable:
                try:
                    os.read(fd, 4096)
                except OSError:
                    pass
            if os.path.exists(BLANK_FLAG):
                wake()

        # Pick up hotplugged devices (USB keyboard, etc.) and drop stale fds.
        if time.monotonic() - last_rescan > RESCAN_EVERY_S:
            for fd, path in list(fds.items()):
                if not os.path.exists(path):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    del fds[fd]
            existing = set(fds.values())
            for path in glob.glob("/dev/input/event*"):
                if path not in existing:
                    try:
                        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                        fds[fd] = path
                    except OSError:
                        continue
            last_rescan = time.monotonic()


if __name__ == "__main__":
    main()
