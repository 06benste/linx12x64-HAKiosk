#!/usr/bin/env python3
"""Rebuild ventoy/firmware-inject.tar.gz from firmware/brcm/.

Run this after touching any file in firmware/brcm/ that the Debian installer's
"Detect network hardware" firmware prompt needs. Ventoy's Injection plugin
(see ventoy/ventoy.json) extracts this archive into the live installer's
initramfs at boot — that's what lets Wi-Fi firmware load automatically instead
of the installer prompting for removable media (which doesn't reliably find
files on a Ventoy data partition — confirmed on real hardware, see
ventoy/README.md).
"""
from __future__ import annotations

import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "firmware" / "brcm"
OUT = ROOT / "ventoy" / "firmware-inject.tar.gz"

# Only the Wi-Fi firmware the installer's hw-detect step actually asks for
# (generic name + this tablet's DMI-matched name). Bluetooth .hcd and the raw
# 4345r6nvram.txt source aren't needed pre-install — those are installed
# separately, post-boot, by scripts/01-wifi-firmware.sh.
FILES = [
    "brcmfmac43455-sdio.txt",
    "brcmfmac43455-sdio.bin",
    "brcmfmac43455-sdio.clm_blob",
    "brcmfmac43455-sdio.LINX-LINX12X64.txt",
    "brcmfmac43455-sdio.LINX-LINX12X64.bin",
    "brcmfmac43455-sdio.LINX-LINX12X64.clm_blob",
]


def main() -> int:
    missing = [f for f in FILES if not (SRC / f).exists()]
    if missing:
        print(f"Missing source files in {SRC}: {missing}")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(OUT, "w:gz") as tf:
        for name in FILES:
            arcname = f"lib/firmware/brcm/{name}"
            tf.add(SRC / name, arcname=arcname)
            print(f"added {arcname}")

    print(f"\nWrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
