#!/usr/bin/env python3
from pathlib import Path
import numpy as np
from PIL import Image

OUT = Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
im = np.asarray(Image.open(OUT / "live_wrap.jpg").convert("RGB"), dtype=np.float32)
h, w, _ = im.shape
g0 = im.mean(axis=2)

def metrics(S: int) -> dict:
    rolled = np.concatenate([im[:, S:], im[:, :S]], axis=1)
    g = rolled.mean(axis=2)
    means = g.mean(axis=0)
    sw = max(8, w // 12)
    l = means[:sw] - means[:sw].mean()
    r = means[-sw:] - means[-sw:].mean()
    denom = (np.linalg.norm(l) * np.linalg.norm(r)) or 1.0
    corr = float(np.dot(l, r) / denom)
    grads = np.mean(np.abs(np.diff(g, axis=1)), axis=0)
    left_band = grads[: max(8, w // 10)]
    right_band = grads[-max(8, w // 10) :]
    return {
        "S": S,
        "corr": corr,
        "left_max": float(left_band.max()),
        "right_max": float(right_band.max()),
        "score": abs(corr) * 20 + float(left_band.max()) + float(right_band.max()),
    }

rows = [metrics(S) for S in range(8, 121)]
rows.sort(key=lambda r: r["score"])
for r in rows[:12]:
    print(
        f"S={r['S']:3d} score={r['score']:6.2f} corr={r['corr']:+.3f} "
        f"L={r['left_max']:.2f} R={r['right_max']:.2f}"
    )
best = rows[0]["S"]
print("BEST", best)
rolled = np.concatenate([im[:, best:], im[:, :best]], axis=1)
Image.fromarray(rolled.astype(np.uint8)).save(OUT / "chosen_roll.jpg")
# sensor equivalent for pre-scale roll on 1600 with crop 1584
print("sensor_wrap", round(best * 1584 / 800))
