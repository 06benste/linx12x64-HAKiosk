#!/usr/bin/env python3
"""One-shot test: force CHGLED off, wait 20s, restore it exactly — with
charger/battery sysfs checked before/during/after to confirm charging
itself is unaffected (REG32H's LED bits are documented as independent of
the charging-control registers, this proves it empirically rather than
just trusting the datasheet).

Only ever touches bits 5,4,3 of REG32H (the CHGLED pattern + control-source
bits) — every other bit is read fresh at the start and preserved exactly,
never assumed/hardcoded, and the register is restored to the *exact*
original value read at startup, not a guessed "on" value.

Run directly on the tablet: sudo python3 scripts/_chgled_toggle_test.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time

I2C_BUS = 6
I2C_ADDR = "0x34"
REG_CHGLED = "0x32"

BATTERY = pathlib.Path("/sys/class/power_supply/axp288_fuel_gauge")
CHARGER = pathlib.Path("/sys/class/power_supply/axp288_charger")

LED_BITS_MASK = 0b0011_1000  # bits 5,4,3
CLEAR_LED_BITS = 0xFF & ~LED_BITS_MASK  # 0xC7 — AND-mask that zeroes just those bits


def i2cget(reg: str) -> int:
    r = subprocess.run(
        ["i2cget", "-y", "-f", str(I2C_BUS), I2C_ADDR, reg],
        capture_output=True, text=True, check=True,
    )
    return int(r.stdout.strip(), 16)


def i2cset(reg: str, val: int) -> None:
    subprocess.run(
        ["i2cset", "-y", "-f", str(I2C_BUS), I2C_ADDR, reg, hex(val & 0xFF)],
        check=True,
    )


def read_sysfs(path: pathlib.Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return "?"


def report(label: str) -> int:
    reg = i2cget(REG_CHGLED)
    status = read_sysfs(BATTERY / "status")
    capacity = read_sysfs(BATTERY / "capacity")
    current = read_sysfs(BATTERY / "current_now")
    voltage = read_sysfs(BATTERY / "voltage_now")
    online = read_sysfs(CHARGER / "online")
    print(
        f"[{label:>16}] REG32H=0x{reg:02x}  battery: {capacity}% {status} "
        f"I={current}uA V={voltage}uV  plugged_in={online == '1'}"
    )
    return reg


def main() -> None:
    print("=== baseline ===")
    original = report("before")

    print("\n=== forcing CHGLED off (Hi-Z, manual mode) — check the LED now ===")
    off_value = original & CLEAR_LED_BITS
    i2cset(REG_CHGLED, off_value)
    time.sleep(0.5)
    after_off = report("after-off-write")
    if after_off != off_value:
        print(f"WARNING: write did not take — expected 0x{off_value:02x}, read back 0x{after_off:02x}")

    print("\n=== waiting 20s ===")
    for i in range(20, 0, -1):
        sys.stdout.write(f"\r  {i:2d}s remaining — LED should be OFF right now...  ")
        sys.stdout.flush()
        time.sleep(1)
    print()
    report("after-20s-wait")

    print("\n=== restoring original register value (back to AUTO) — check the LED now ===")
    i2cset(REG_CHGLED, original)
    time.sleep(0.5)
    final = report("after-restore")

    print()
    if final == original:
        print(f"OK — register restored exactly to original 0x{original:02x}.")
    else:
        print(f"WARNING — restore mismatch: expected 0x{original:02x}, got 0x{final:02x}")


if __name__ == "__main__":
    main()
