#!/usr/bin/env python3
from pathlib import Path
import numpy as np
from PIL import Image

OUT = Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
arr = np.asarray(Image.open(OUT / "live_wrap.jpg").convert("RGB"), dtype=np.float32)
g = arr.mean(axis=2)
h, w = g.shape

def col_diff(a, b):
    return float(np.mean(np.abs(g[:, a] - g[:, b])))

print("edge continuity (col0 vs col-1):", col_diff(0, w - 1))
print("seam@25:", col_diff(24, 25))
print("seam@17:", col_diff(16, 17))
print("mid:", col_diff(w // 2 - 1, w // 2))

# If circular wrap, edge continuity should be better than seam
# Search S that maximizes (seam_grad / edge_grad) and after-roll join continuity
best = None
for S in range(8, 200):
    seam = col_diff(S - 1, S)
    # after roll, join at w-S between old w-1 and old 0
    join = col_diff(w - 1, 0)  # same for all S if pure circular!
    # score: high seam at S, and after roll the max interior grad drops
    rolled = np.concatenate([g[:, S:], g[:, :S]], axis=1)
    grads = np.mean(np.abs(np.diff(rolled, axis=1)), axis=0)
    # exclude very edges
    interior_max = float(grads[2:-2].max())
    interior_mean = float(grads.mean())
    score = seam - interior_max  # want high original seam, low after
    if best is None or score > best[0]:
        best = (score, S, seam, interior_max, interior_mean)
print("best S", best)

# Save fix_roll_25 and cropaway for visual
for S in (17, 25, 48, 80):
    rolled = np.concatenate([arr[:, S:], arr[:, :S]], axis=1)
    Image.fromarray(rolled.astype(np.uint8)).save(OUT / f"fix_roll_{S}.jpg")
    # also crop-away (discard left S px, scale back)
    cropped = arr[:, S:, :]
    Image.fromarray(cropped.astype(np.uint8)).resize((w, h), Image.Resampling.BILINEAR).save(
        OUT / f"fix_discard_{S}.jpg"
    )
print("saved")
