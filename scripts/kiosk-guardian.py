#!/usr/bin/env python3
"""Secondary power/thermal mitigations: dim on low battery, cut the camera
if it's running hot.

Deliberately separate from battery-guard.py: both of these depend on
power-api.py being reachable, which is fine here (worst case if it's down
is just "didn't dim" / "didn't cut power to the camera"), but battery-guard's
own job — the critical shutdown-before-hard-cut path — stays dependency-free
on purpose. Combined into one process rather than two to avoid stacking up
extra always-on Python interpreters on a device this session was already
about *reducing* resource draw on.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:17823"
CHECK_INTERVAL_S = 15

DIM_BATTERY_PERCENT = 20
DIM_BRIGHTNESS_PERCENT = 15

# Cherry Trail's Z8350 has a small TDP; junction limits are typically well
# above this, but there's no reason to keep a non-essential heat source
# (the camera's ISP + continuous encode) running once things are clearly
# elevated. Debounced over several readings — thermal drift is gradual
# (unlike the battery's observed ~60s full-drain), so there's no need for
# battery-guard's react-on-first-reading urgency here.
THERMAL_LIMIT_C = 85.0
THERMAL_CONFIRM_READS = 3


def log(msg: str) -> None:
    subprocess.run(["logger", "-t", "ha-kiosk-guardian", msg], check=False)


def api_get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}", timeout=8) as resp:
        return json.loads(resp.read().decode())


def api_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}", data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def find_battery() -> pathlib.Path | None:
    root = pathlib.Path("/sys/class/power_supply")
    if not root.exists():
        return None
    for d in sorted(root.iterdir()):
        try:
            if (d / "type").read_text().strip() == "Battery":
                return d
        except OSError:
            continue
    return None


def main() -> None:
    battery = find_battery()
    dimmed = False
    hot_streak = 0

    while True:
        time.sleep(CHECK_INTERVAL_S)

        # --- low-battery dim ---
        if battery is not None:
            try:
                cap = int((battery / "capacity").read_text().strip())
                status = (battery / "status").read_text().strip().lower()
                low = cap <= DIM_BATTERY_PERCENT and status == "discharging"
                if low and not dimmed:
                    try:
                        api_post("/brightness", {"percent": DIM_BRIGHTNESS_PERCENT})
                        dimmed = True
                        log(f"battery {cap}% discharging — dimmed to {DIM_BRIGHTNESS_PERCENT}%")
                    except (urllib.error.URLError, OSError) as exc:
                        log(f"dim request failed: {exc}")
                elif not low and dimmed:
                    # Recovered — don't auto-restore brightness (that would
                    # fight whatever the user sets afterward); just clear the
                    # latch so a future dip dims again.
                    dimmed = False
                    log(f"battery {cap}% status={status} — recovered, dim latch cleared")
            except (OSError, ValueError):
                pass

        # --- thermal camera cutoff ---
        try:
            status = api_get("/status")
            thermal = status.get("thermal") or {}
            temp = thermal.get("cpu_c")
            if temp is None:
                temp = thermal.get("soc_c")
            camera_on = bool((status.get("camera") or {}).get("power"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            continue

        if temp is not None and temp >= THERMAL_LIMIT_C and camera_on:
            hot_streak += 1
        else:
            hot_streak = 0

        # The camera_on check above already means this can't refire once the
        # camera's actually off — no separate "already cut" flag needed.
        if hot_streak >= THERMAL_CONFIRM_READS:
            try:
                api_post("/camera", {"on": False})
                log(f"CPU {temp}C >= {THERMAL_LIMIT_C}C for {hot_streak} readings — camera turned off")
            except (urllib.error.URLError, OSError) as exc:
                log(f"camera cutoff request failed: {exc}")
            hot_streak = 0


if __name__ == "__main__":
    main()
