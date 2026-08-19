#!/usr/bin/env python3
"""Capture + grade one JPEG using the approved Linx camera look."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camera_preview import PreviewLook, apply_preview  # noqa: E402

CFG = Path(os.environ.get("CAMERA_PREVIEW_JSON", "/opt/ha-kiosk/config/camera_preview.json"))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ha-kiosk-camera.jpg")


def main() -> int:
    look = PreviewLook.load(CFG if CFG.exists() else None)
    frames = 2
    try:
        data = json.loads(CFG.read_text(encoding="utf-8"))
        fr = data.get("capture", {}).get("frames")
        if fr:
            frames = int(fr)
    except Exception:
        pass

    subprocess.run(
        ["/opt/ha-kiosk/scripts/load-atomisp.sh"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["pkill", "-9", "-f", "v4l2-ctl --stream"], check=False)
    # Do not pkill ffmpeg — the live MJPEG service may be using it.
    raw = Path(tempfile.mkstemp(prefix="ha-cam-", suffix=".raw")[1])
    try:
        subprocess.run(
            [
                "timeout",
                "-s",
                "KILL",
                "25",
                "v4l2-ctl",
                "-d",
                "/dev/video0",
                "--set-fmt-video=width=1600,height=1200,pixelformat=NV12",
                "--stream-mmap=4",
                f"--stream-count={frames}",
                f"--stream-to={raw}",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not raw.exists() or raw.stat().st_size < 100000:
            print(f"capture failed (raw={raw.stat().st_size if raw.exists() else 0})", file=sys.stderr)
            return 2
        jpg = Path(tempfile.mkstemp(prefix="ha-cam-", suffix=".jpg")[1])
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "nv12",
                    "-s",
                    "1600x1184",
                    "-i",
                    str(raw),
                    "-vf",
                    "crop=1584:1184:0:0",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    "-update",
                    "1",
                    str(jpg),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            graded = apply_preview(Image.open(jpg), look)
            OUT.parent.mkdir(parents=True, exist_ok=True)
            graded.save(OUT, quality=92)
            print(f"OK {OUT} size={OUT.stat().st_size}")
            return 0
        finally:
            jpg.unlink(missing_ok=True)
    finally:
        raw.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
