#!/usr/bin/env python3
"""Detect per-row horizontal shear / wrap amount in live_wrap.jpg."""
from pathlib import Path

import numpy as np
from PIL import Image

im = np.asarray(Image.open(Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag\live_wrap.jpg")).convert("L"), dtype=np.float32)
h, w = im.shape
# Correlate each row against middle row to estimate shift
ref = im[h // 2]
shifts = []
for y in range(0, h, 8):
    row = im[y]
    # circular correlation via FFT for shift
    f = np.fft.fft(row - row.mean())
    g = np.fft.fft(ref - ref.mean())
    corr = np.fft.ifft(f * np.conj(g)).real
    sh = int(np.argmax(corr))
    if sh > w // 2:
        sh -= w
    shifts.append((y, sh, float(corr.max())))
print("row shifts vs mid (sample):")
for y, sh, p in shifts[:: max(1, len(shifts)//12)]:
    print(f"  y={y:3d} shift={sh:4d} peak={p:.0f}")
# Estimate constant circular shift of whole image: correlate left edge column pattern
# Better: for each candidate wrap W, score vertical seam energy at x=W vs average
print("\nseam energy by x:")
gray = im
best = None
for x in range(4, w // 3):
    # seam strength = mean abs diff across columns x-1 and x, normalized
    seam = float(np.mean(np.abs(gray[:, x] - gray[:, x - 1])))
    # also check if left[:x] matches right[-x:] under roll
    left = gray[:, :x]
    right = gray[:, -x:]
    mse = float(np.mean((left - right) ** 2))
    # continuity after hypothetical roll
    rolled = np.concatenate([gray[:, x:], gray[:, :x]], axis=1)
    # new seam should be low at junction... after roll the junction is at w-x
    j = w - x
    # compare continuity at left edge of rolled (should join former x and x-1 from original... 
    # after roll, pixel 0 was old x, pixel -1 was old x-1 — adjacent in original!
    cont = float(np.mean(np.abs(rolled[:, 0] - rolled[:, -1])))  # these WERE neighbors
    # Actually after correct roll, left and right edges are NOT neighbors.
    # Continuity metric: mean gradient at every column; the anomalous seam column disappears
    grads = np.mean(np.abs(np.diff(rolled.astype(np.float32), axis=1)), axis=0)
    max_grad = float(grads.max())
    mean_grad = float(grads.mean())
    # score: how much left matches right (for wrap) + low residual seam
    score = mse + seam * 10
    if best is None or score < best[0]:
        best = (score, x, seam, mse, max_grad, mean_grad)
    if x % 8 == 0 or (40 <= x <= 120 and x % 4 == 0):
        print(f"  x={x:3d} seam={seam:.2f} LvsR_mse={mse:.1f} maxg={max_grad:.2f}")
print("BEST", best)

# Also check shear: cumulative shift
print("\nmedian abs row-shift", float(np.median([abs(s) for _, s, _ in shifts])))
print("mean row-shift", float(np.mean([s for _, s, _ in shifts])))
