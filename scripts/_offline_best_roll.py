#!/usr/bin/env python3
"""Offline: find best horizontal roll on a good graded frame."""
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
src = OUT / "live_wrap.jpg"
im = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32)
h, w, _ = im.shape
g = im.mean(axis=2)
grads0 = np.mean(np.abs(np.diff(g, axis=1)), axis=0)
print("original leftMax", float(grads0[: w // 8].max()), "rightMax", float(grads0[-w // 8 :].max()))

best = None
for S in range(4, 200):
    rolled = np.concatenate([im[:, S:], im[:, :S]], axis=1)
    rg = rolled.mean(axis=2)
    grads = np.mean(np.abs(np.diff(rg, axis=1)), axis=0)
    left_max = float(grads[: w // 8].max())
    right_max = float(grads[-w // 8 :].max())
    # join continuity: after roll, former neighbors at S-1/S are at edges — ignore
    # prefer low edge seams; also low max overall in outer bands
    score = left_max + right_max
    if best is None or score < best[0]:
        best = (score, S, left_max, right_max)
        Image.fromarray(rolled.astype(np.uint8)).save(OUT / "best_offline_roll.jpg")

print("BEST_DISPLAY_ROLL", best)
# Map display roll to sensor roll roughly: display is after crop 1584->800
# Original live_wrap used crop x=0 then scale, so display_px * 1584/800 ~= sensor
sensor = int(round(best[1] * 1584 / 800))
print("SENSOR_WRAP_EST", sensor)
# Also try sensor candidates around that, simulating crop after roll on 800-space is enough

# Save a few neighbors
for S in range(max(4, best[1] - 20), best[1] + 21, 4):
    rolled = np.concatenate([im[:, S:], im[:, :S]], axis=1)
    Image.fromarray(rolled.astype(np.uint8)).save(OUT / f"off_roll_{S}.jpg")
print("wrote neighbors")
