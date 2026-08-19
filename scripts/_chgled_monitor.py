#!/usr/bin/env python3
"""Live, read-only monitor for the AXP288's CHGLED (charge indicator LED),
ahead of actually writing to it — shows both the raw register state and a
prediction of what the LED is actually doing right now.

Demonstrates reading REG32H/REG34H via the same i2c-dev + i2c-tools path
this project already uses for direct camera-sensor register access (see
gc2355_hw_exposure.py) — applied here to the PMIC instead. Never writes;
just polls and decodes.

Why a prediction, not just the raw register: REG32H[5:4] (the blink-pattern
bits) only drive the pin when REG32H[3]=0 (manual mode). This board runs in
AUTO mode (REG32H[3]=1) — there, the charger's own state machine drives the
pin directly per the "Charge LED indicator" table (AXP288C datasheet
§9.4.4, Table 9-32), and REG32H[5:4] is simply ignored. So the actual
on/off/blink state has to be *derived* from real charge status per that
table, not read as a static register value. Verified against the datasheet
page image directly (not just the flattened PDF text, which scrambled the
table's column order) — this board is confirmed running "Type B" via
REG34H bit4, so that's the column implemented here:

  CHGLED pin      | Type B meaning
  ----------------|------------------------------------------------
  Z (tri-state)   | Not charging (no/insufficient power, or discharging)
  25% duty @ 1Hz  | Charging
  25% duty @ 4Hz  | Alarm (VBUS>6.3V, charger timeout, IC overheat, or
                  |   battery OVP/UVP)
  Low (solid)     | Not charging — battery fully charged

Run directly on the tablet: sudo python3 scripts/_chgled_monitor.py
"""
from __future__ import annotations

import pathlib
import subprocess
import time

I2C_BUS = 6
I2C_ADDR = "0x34"
REG_CHGLED = "0x32"  # REG32H: bits[5:4] pattern, bit3 control source, bit6 batt-detect
REG_MODE = "0x34"  # REG34H: bit4 selects Type A/B (only used when REG32H bit3=1)

BATTERY = pathlib.Path("/sys/class/power_supply/axp288_fuel_gauge")
CHARGER = pathlib.Path("/sys/class/power_supply/axp288_charger")

MANUAL_PATTERNS = {
    0: "Hi-Z (off)",
    1: "25% duty @ 0.5Hz (slow blink)",
    2: "25% duty @ 2Hz (fast blink)",
    3: "drive low (solid on)",
}


def i2cget(reg: str) -> int | None:
    r = subprocess.run(
        ["i2cget", "-y", "-f", str(I2C_BUS), I2C_ADDR, reg],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    try:
        return int(r.stdout.strip(), 16)
    except ValueError:
        return None


def read_sysfs(path: pathlib.Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return "?"


def decode_register(reg32: int, reg34: int) -> tuple[bool, str, str]:
    """Returns (auto_mode, mode_type, raw_description)."""
    pattern_bits = (reg32 >> 4) & 0b11
    auto = bool(reg32 & 0b0000_1000)
    batt_detect = bool(reg32 & 0b0100_0000)
    mode_type = "B" if (reg34 & 0b0001_0000) else "A"
    if auto:
        raw = f"AUTO (charger-driven, Type {mode_type} table) — bits[5:4] not used while auto"
    else:
        raw = f"MANUAL: {MANUAL_PATTERNS[pattern_bits]}"
    return auto, mode_type, f"{raw}  (batt_detect={'on' if batt_detect else 'off'})"


def predict_led(mode_type: str, plugged_in: bool, status: str, health: str) -> str:
    """What the LED should actually be doing right now, per Table 9-32."""
    status_l = status.lower()
    health_l = health.lower()
    alarm = health_l not in ("good", "unknown", "?", "")
    if mode_type == "B":
        if alarm:
            return f"FAST BLINK @ 4Hz  — alarm (health={health})"
        if status_l == "charging":
            return "SLOW BLINK @ 1Hz  — charging"
        if status_l == "full":
            return "SOLID ON          — fully charged, not charging"
        return "OFF (tri-state)   — not charging (no/insufficient power, or discharging)"
    # Type A fallback (not what this board uses, but kept correct per datasheet)
    if alarm:
        return f"FAST BLINK @ 4Hz  — overvoltage alarm (health={health})"
    if status_l == "charging":
        return "SOLID ON          — charging"
    if not plugged_in:
        return "OFF (tri-state)   — not charging"
    return "SLOW BLINK @ 1Hz  — abnormality alarm"


def main() -> None:
    print(f"watching CHGLED via i2c bus {I2C_BUS} addr {I2C_ADDR} — Ctrl+C to stop")
    print("(read-only — no i2cset calls in this script)\n")
    while True:
        reg32 = i2cget(REG_CHGLED)
        reg34 = i2cget(REG_MODE)
        if reg32 is None or reg34 is None:
            print("i2c read failed — is i2c-dev loaded? (modprobe i2c-dev)")
            time.sleep(2)
            continue
        status = read_sysfs(BATTERY / "status")
        capacity = read_sysfs(BATTERY / "capacity")
        health = read_sysfs(BATTERY / "health")
        online = read_sysfs(CHARGER / "online")
        plugged_in = online == "1"

        _auto, mode_type, raw_desc = decode_register(reg32, reg34)
        led_state = predict_led(mode_type, plugged_in, status, health)

        ts = time.strftime("%H:%M:%S")
        print(
            f"{ts}  LED: {led_state}\n"
            f"          reg: REG32H=0x{reg32:02x} REG34H=0x{reg34:02x}  {raw_desc}\n"
            f"          battery: {capacity}% {status} (health={health}), plugged_in={plugged_in}"
        )
        time.sleep(1)


if __name__ == "__main__":
    main()
