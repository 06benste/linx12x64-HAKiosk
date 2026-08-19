#!/usr/bin/env python3
"""Force GC2355 exposure/gain over i2c (AtomISP 3A does not drive this sensor)."""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

# Balanced indoor profile from sweep (exp16_g3-ish): real photons, not ffmpeg EV.
# exposure≈1600 lines, mild VBI, analog gain step 3.
DEFAULT_PROFILE = {
    "exposure": 1600,  # lines → regs 0x03/0x04
    "vb": 0x0080,  # regs 0x07/0x08
    "b0": 0x55,
    "b1": 0x03,
    "b2": 0x40,
    "b6": 0x03,  # analog gain (stock was 0x00 → crushed dark)
    "analog_26": 0x01,
}

_ADDR = 0x3C


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _iget(bus: int, reg: int) -> int | None:
    r = _run(["i2cget", "-y", "-f", str(bus), hex(_ADDR), hex(reg)])
    if r.returncode != 0:
        return None
    try:
        return int(r.stdout.strip(), 16)
    except ValueError:
        return None


def _iset(bus: int, reg: int, val: int) -> bool:
    return (
        _run(["i2cset", "-y", "-f", str(bus), hex(_ADDR), hex(reg), hex(val & 0xFF)]).returncode
        == 0
    )


def find_sensor_bus(prefer: int | None = None) -> int | None:
    """prefer: 0=front (GCTI2355:00), 1=rear (GCTI2355:01)."""
    # Userspace i2c needs /dev/i2c-*; load on demand (not always present at boot).
    subprocess.run(
        ["modprobe", "i2c-dev"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    found: list[tuple[str, int]] = []
    for d in sorted(Path("/sys/bus/i2c/devices").glob("i2c-GCTI2355:*")):
        bus: int | None = None
        for p in str(d.resolve()).split("/"):
            if p.startswith("i2c-") and p[4:].isdigit():
                bus = int(p[4:])
        if bus is None:
            continue
        _iset(bus, 0xFE, 0x00)
        if _iget(bus, 0xF0) is not None:
            found.append((d.name, bus))
    if not found:
        return None
    if prefer is not None:
        tag = f"GCTI2355:0{int(prefer)}"
        for name, bus in found:
            if tag in name:
                return bus
    return found[0][1]


def apply_profile(
    profile: dict | None = None,
    bus: int | None = None,
    prefer_input: int | None = None,
) -> dict:
    """Write exposure/gain. Returns status dict."""
    prof = dict(DEFAULT_PROFILE)
    if profile:
        prof.update(profile)
    bus = find_sensor_bus(prefer=prefer_input) if bus is None else bus
    if bus is None:
        return {"ok": False, "error": "sensor i2c not found"}

    exp = int(prof["exposure"]) & 0xFFFF
    vb = int(prof["vb"]) & 0xFFFF
    # GC2355 page 0 must be selected before exposure/gain regs.
    _iset(bus, 0xFE, 0x00)
    _iset(bus, 0x07, (vb >> 8) & 0xFF)
    _iset(bus, 0x08, vb & 0xFF)
    _iset(bus, 0x03, (exp >> 8) & 0xFF)
    _iset(bus, 0x04, exp & 0xFF)
    _iset(bus, 0xB0, int(prof["b0"]) & 0xFF)
    _iset(bus, 0xB1, int(prof["b1"]) & 0xFF)
    _iset(bus, 0xB2, int(prof["b2"]) & 0xFF)
    _iset(bus, 0xB6, int(prof["b6"]) & 0xFF)
    if "analog_26" in prof:
        _iset(bus, 0x26, int(prof["analog_26"]) & 0xFF)
    time.sleep(0.02)

    eh, el = _iget(bus, 0x03), _iget(bus, 0x04)
    got = ((eh or 0) << 8) | (el or 0)
    b6 = _iget(bus, 0xB6)
    return {
        "ok": got == exp and b6 == (int(prof["b6"]) & 0xFF),
        "bus": bus,
        "exposure": got,
        "b6": b6,
        "b0": _iget(bus, 0xB0),
        "vb": ((_iget(bus, 0x07) or 0) << 8) | (_iget(bus, 0x08) or 0),
    }


class HwExposureKeeper(threading.Thread):
    """Re-apply sensor exposure while stream runs (ISP does not drive GC2355 AE)."""

    def __init__(
        self,
        stop_event: threading.Event,
        interval_s: float = 5.0,
        input_getter=None,
    ) -> None:
        super().__init__(daemon=True, name="gc2355-hw-exp")
        self._stop = stop_event
        self._interval = interval_s
        self._input_getter = input_getter
        self.last: dict = {}

    def run(self) -> None:
        # Wait for MIPI/stream to settle before first forced write (avoids bus fights).
        if self._stop.wait(2.5):
            return
        prefer = None
        try:
            prefer = int(self._input_getter()) if self._input_getter else None
        except Exception:
            prefer = None
        self.last = apply_profile(prefer_input=prefer)
        print(f"gc2355 hw exposure apply {self.last}", flush=True)
        while not self._stop.wait(self._interval):
            prefer = None
            try:
                prefer = int(self._input_getter()) if self._input_getter else None
            except Exception:
                prefer = None
            st = apply_profile(prefer_input=prefer)
            self.last = st
            if not st.get("ok"):
                print(f"gc2355 hw exposure refresh failed {st}", flush=True)
