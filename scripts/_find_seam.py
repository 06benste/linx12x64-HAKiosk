#!/usr/bin/env python3
"""Find strongest vertical seam; generate rolled previews around it."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUT = Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
im = Image.open(OUT / "live_wrap.jpg").convert("RGB")
arr = np.asarray(im, dtype=np.float32)
gray = arr.mean(axis=2)
h, w = gray.shape

grads = np.mean(np.abs(np.diff(gray, axis=1)), axis=0)
# top peaks
idx = np.argsort(grads)[::-1][:15]
print("top seam columns (0-based left of edge):")
for i in idx:
    print(f"  x={i+1:4d} grad={grads[i]:.2f}")

# Mark seams on a copy
vis = im.copy()
draw = ImageDraw.Draw(vis)
for i in idx[:5]:
    x = int(i + 1)
    draw.line([(x, 0), (x, h - 1)], fill=(255, 0, 0), width=2)
vis.save(OUT / "live_wrap_seams.jpg")

peak = int(idx[0] + 1)
print("PEAK_SEAM_X", peak)

# For wrap fix: if left strip is misplaced right-edge content, roll by peak
for sw in sorted(set([peak, peak - 2, peak + 2, 16, 24, 32, 40, 48, 64, 72, 80])):
    if sw < 4 or sw >= w // 2:
        continue
    rolled = np.concatenate([arr[:, sw:], arr[:, :sw]], axis=1)
    # score: max vertical gradient should drop near old seam area
    g2 = np.mean(np.abs(np.diff(rolled.mean(axis=2), axis=1)), axis=0)
    # continuity at join: rolled[:,0] was arr[:,sw], rolled[:,-1] was arr[:,sw-1] — neighbors
    join = float(np.mean(np.abs(rolled[:, 0] - rolled[:, -1])))
    print(
        f"roll {sw:3d}: max_grad={g2.max():.2f} mean_grad={g2.mean():.2f} "
        f"edge_pair(should_be_neighbors)={join:.2f}"
    )
    Image.fromarray(rolled.astype(np.uint8)).save(OUT / f"fix_roll_{sw}.jpg")

# Also try: crop away left peak strip (discard) instead of rolling
cropped = arr[:, peak:]
# pad or stretch
Image.fromarray(cropped.astype(np.uint8)).resize((w, h)).save(OUT / f"fix_cropaway_{peak}.jpg")
print("wrote previews")
