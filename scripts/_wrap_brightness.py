#!/usr/bin/env python3
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

OUT = Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
im = Image.open(OUT / "live_wrap.jpg").convert("RGB")
arr = np.asarray(im, dtype=np.float32)
g = arr.mean(axis=2)
h, w = g.shape

# Column mean brightness profile for left 200px
means = g.mean(axis=0)
print("col mean brightness (0..200):")
for x in range(0, 201, 4):
    print(f"  x={x:3d} mean={means[x]:5.1f}  {'*' * int(means[x]/4)}")

# The wrap strip is bright wall; main starts with dark blind.
# Find first column where brightness drops below threshold and stays low
bright = means > 40
# find end of initial bright region (allowing small gaps)
end = 0
for x in range(0, 200):
    if means[x] > 35:
        end = x
    elif x > 10 and means[x] < 25:
        # check next 20 cols mostly dark
        if means[x : x + 20].mean() < 30:
            end = x
            break
print("brightness_transition_x", end)

# Manual: compare left strip of width S to right strip — use STRUCTURAL
# similarity via normalized cross-correlation of column-mean profiles
print("\nleft-profile vs right-profile correlation by S:")
best = None
for S in range(8, 160):
    left = means[:S]
    right = means[-S:]
    # pearson
    l = left - left.mean()
    r = right - right.mean()
    denom = (np.linalg.norm(l) * np.linalg.norm(r)) or 1.0
    corr = float(np.dot(l, r) / denom)
    # also mse of full 2D strips (center band to avoid chairs)
    band = g[100:400, :]
    mse = float(np.mean((band[:, :S] - band[:, -S:]) ** 2))
    score = corr - mse / 10000
    if best is None or score > best[0]:
        best = (score, S, corr, mse)
    if S % 8 == 0:
        print(f"  S={S:3d} corr={corr:+.3f} mse={mse:.0f}")
print("BEST_PROFILE", best)

S = best[1]
vis = im.copy()
draw = ImageDraw.Draw(vis)
draw.line([(S, 0), (S, h - 1)], fill=(0, 255, 0), width=3)
vis.save(OUT / "live_wrap_guess.jpg")

rolled = np.concatenate([arr[:, S:], arr[:, :S]], axis=1)
Image.fromarray(rolled.astype(np.uint8)).save(OUT / "fix_roll_best.jpg")
discard = arr[:, S:]
Image.fromarray(discard.astype(np.uint8)).resize((w, h)).save(OUT / "fix_discard_best.jpg")

# Try S around brightness transition too
for S2 in sorted(set([end, end - 4, end + 4, 48, 56, 64, 72, 80, 88, 96])):
    if S2 < 8:
        continue
    rolled = np.concatenate([arr[:, S2:], arr[:, :S2]], axis=1)
    Image.fromarray(rolled.astype(np.uint8)).save(OUT / f"fix_roll_{S2}.jpg")
print("S_best", S, "S_bright", end)
