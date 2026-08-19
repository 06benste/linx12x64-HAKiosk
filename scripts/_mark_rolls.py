#!/usr/bin/env python3
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

OUT = Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
im = np.asarray(Image.open(OUT / "live_wrap.jpg").convert("RGB"), dtype=np.uint8)
h, w, _ = im.shape

for S in (20, 40, 60, 80, 100, 120, 140, 157, 180):
    rolled = np.concatenate([im[:, S:], im[:, :S]], axis=1)
    vis = Image.fromarray(rolled)
    draw = ImageDraw.Draw(vis)
    # mark where strip was appended (join at w-S)
    j = w - S
    draw.line([(j, 0), (j, h - 1)], fill=(0, 255, 0), width=2)
    vis.save(OUT / f"mark_roll_{S}.jpg")
print("wrote marked rolls")
