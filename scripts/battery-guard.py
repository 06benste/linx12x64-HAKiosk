#!/usr/bin/env python3
"""Clean shutdown when running on battery and capacity drops critically low.

Deliberately independent of power-api.py (reads /sys/class/power_supply
directly) so it keeps working even if that service is down — this is the
last line of defense against an unclean power-loss shutdown, so it should
have as few dependencies as possible.

Reacts on the first qualifying reading rather than debouncing over several
samples: on this hardware the battery has been observed dropping from 2% to
0% in about a minute once it starts falling, so a multi-sample confirmation
delay risks losing the race against the hardware's own low-voltage cutoff.
A stray single misread just means shutting down a percent or two early,
which is a far smaller cost than an unclean crash.
"""
from __future__ import annotations

import pathlib
import subprocess
import time

THRESHOLD_PERCENT = 1
CHECK_INTERVAL_S = 8


def _read_int(path: pathlib.Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _find_power_supply(types: tuple[str, ...]) -> pathlib.Path | None:
    root = pathlib.Path("/sys/class/power_supply")
    if not root.exists():
        return None
    for d in sorted(root.iterdir()):
        try:
            typ = (d / "type").read_text().strip()
        except OSError:
            continue
        if typ in types:
            return d
    return None


def _is_discharging(battery: pathlib.Path) -> bool:
    try:
        return battery.joinpath("status").read_text().strip().lower() == "discharging"
    except OSError:
        return False


def log(msg: str) -> None:
    subprocess.run(["logger", "-t", "ha-kiosk-battery-guard", msg], check=False)


def main() -> None:
    battery = _find_power_supply(("Battery",))
    if battery is None:
        log("no Battery power_supply on this hardware — nothing to guard, exiting")
        return
    log(f"watching {battery.name}, threshold={THRESHOLD_PERCENT}% interval={CHECK_INTERVAL_S}s")

    while True:
        time.sleep(CHECK_INTERVAL_S)
        cap = _read_int(battery / "capacity")
        if cap is None or cap > THRESHOLD_PERCENT:
            continue
        # Gate on the fuel gauge's own charge/discharge status, not whether a
        # cable is plugged in — confirmed on this hardware that "online"=1
        # (AC/USB detected) does not guarantee net-positive current: an
        # inadequate charger can leave the battery discharging the entire
        # time it's "plugged in". What actually predicts an imminent
        # low-voltage hard-cut is net current direction, so that's what this
        # checks instead.
        if not _is_discharging(battery):
            continue
        log(f"battery critical ({cap}%, discharging) — shutting down cleanly")
        subprocess.run(["systemctl", "poweroff"], check=False)
        return


if __name__ == "__main__":
    main()
