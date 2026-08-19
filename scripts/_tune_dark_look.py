#!/usr/bin/env python3
"""Probe v4l2 ctrls and try a cleaner fixed look offline on last plain snap."""
from __future__ import annotations

import io
import pathlib
import sys

import paramiko
from PIL import Image, ImageEnhance, ImageFilter, ImageStat

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
sys.path.insert(0, str(ROOT / "scripts"))
from camera_preview import AutoLookState, AutoSettings, PreviewLook, apply_preview  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    # stop stream briefly to free device for --all, or use --list-ctrls while busy
    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash -lc "
        f"{repr('v4l2-ctl -d /dev/video0 --list-ctrls 2>&1 | head -n 80')}",
        timeout=30,
        get_pty=True,
    )
    print(o.read().decode("utf-8", "replace")[-4000:])

    plain = Image.open(OUT / "plain.jpg").convert("RGB")
    candidates = {
        "orig_approved": PreviewLook(exposure_ev=-0.03, contrast=1.02, saturation=1.08, wb_r=1.35, wb_g=0.91, wb_b=1.00, shadows=0.0, highlights=0.0),
        "dark_room": PreviewLook(exposure_ev=1.2, contrast=1.04, saturation=1.05, wb_r=1.40, wb_g=0.92, wb_b=1.05, shadows=0.28, highlights=0.10),
        "dark_clean": PreviewLook(exposure_ev=1.0, contrast=1.03, saturation=1.0, wb_r=1.42, wb_g=0.90, wb_b=1.08, shadows=0.35, highlights=0.08),
    }
    for name, look in candidates.items():
        img = apply_preview(plain, look)
        # light denoise
        img2 = img.filter(ImageFilter.MedianFilter(size=3))
        st = ImageStat.Stat(img2)
        path = OUT / f"cand_{name}.jpg"
        img2.save(path, quality=90)
        print(name, [round(x, 1) for x in st.mean], path)
    c.close()


if __name__ == "__main__":
    main()
