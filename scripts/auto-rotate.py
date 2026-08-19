#!/usr/bin/env python3
"""Auto-rotate the kiosk display based on the onboard accelerometer
(i2c-KIOX000A, standard kernel IIO driver — /sys/bus/iio/devices/iio:device0).

Calls power-api's existing /rotate action — the same one the drawer's
manual rotate buttons already use — so the actual apply mechanism
(persisted ROTATION_FILE + chromium-extension/rotation.js re-reading it)
is unchanged; this only decides *when* to call it.

Orientation is derived from whichever of the X/Y axes currently has the
larger gravity component (Z — face-up/face-down tilt — is ignored, since
the screen is always meant to face the viewer). Requires several
consecutive stable readings agreeing before acting, so bumping the desk
or briefly picking the tablet up doesn't flip the display.

The raw-axis-to-screen-direction mapping below was calibrated live against
the real device (rotate it through all four orientations, applied /rotate
via the API, visually confirmed each one) — see ORIENTATION_TO_ROTATION.

DRY-RUN BY DEFAULT (AUTO_ROTATE_LIVE unset or "0"): logs what it *would*
do without ever calling /rotate.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:17823"
ACCEL = pathlib.Path("/sys/bus/iio/devices/iio:device0")
CHECK_INTERVAL_S = 1.0
STABLE_READINGS_REQUIRED = 3  # ~3s of agreement before committing a change
LIVE = os.environ.get("AUTO_ROTATE_LIVE", "0").strip() in ("1", "true", "yes")

# Mapping from "which axis dominates, which sign" to power-api's rotation
# direction values (normal/left/right/inverted) — calibrated live against
# the real device: x-/x+ confirmed correct (upright/upside-down). The y
# pair was first tried as y+ -> right / y- -> left based on a manual
# /rotate + /refresh test, but running live showed that was backwards —
# corrected here to y+ -> left / y- -> right.
ORIENTATION_TO_ROTATION = {
    "x-": "normal",
    "x+": "inverted",
    "y+": "left",
    "y-": "right",
}


def log(msg: str) -> None:
    subprocess.run(["logger", "-t", "ha-kiosk-auto-rotate", msg], check=False)
    print(msg, flush=True)


def read_axis(name: str) -> float | None:
    try:
        raw = int((ACCEL / f"in_accel_{name}_raw").read_text().strip())
        scale = float((ACCEL / "in_accel_scale").read_text().strip())
        return raw * scale
    except (OSError, ValueError):
        return None


def classify(x: float, y: float) -> str | None:
    """Returns one of ORIENTATION_TO_ROTATION's keys, or None if the
    reading is too small/ambiguous to trust (e.g. tablet lying flat, where
    neither X nor Y carries much of the gravity vector)."""
    if abs(x) < 1.5 and abs(y) < 1.5:
        return None
    if abs(x) >= abs(y):
        return "x+" if x > 0 else "x-"
    return "y+" if y > 0 else "y-"


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


def current_rotation() -> str:
    try:
        return api_get("/status").get("rotation", "normal")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return "normal"


def main() -> None:
    if not ACCEL.exists():
        log("no accelerometer at " + str(ACCEL) + " — nothing to do, exiting")
        return
    log(f"watching accelerometer, {'LIVE' if LIVE else 'DRY-RUN (no /rotate calls)'}")

    last_stable = None
    streak = 0
    applied = current_rotation()

    while True:
        time.sleep(CHECK_INTERVAL_S)
        x = read_axis("x")
        y = read_axis("y")
        if x is None or y is None:
            continue

        orientation = classify(x, y)
        if orientation is None:
            streak = 0
            continue

        if orientation == last_stable:
            streak += 1
        else:
            last_stable = orientation
            streak = 1

        if streak < STABLE_READINGS_REQUIRED:
            continue

        direction = ORIENTATION_TO_ROTATION[orientation]
        if direction == applied:
            continue

        if LIVE:
            try:
                api_post("/rotate", {"direction": direction})
                log(f"x={x:.2f} y={y:.2f} orientation={orientation} -> rotated to {direction}")
            except (urllib.error.URLError, OSError) as exc:
                log(f"rotate request failed: {exc}")
                continue
        else:
            log(f"[dry-run] x={x:.2f} y={y:.2f} orientation={orientation} -> would rotate to {direction} (currently {applied})")
        applied = direction


if __name__ == "__main__":
    main()
