#!/usr/bin/env python3
"""Measure left-strip vs right-strip similarity for crop offset candidates."""
from pathlib import Path

from PIL import Image
import numpy as np

OUT = Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")


def score(path: Path, strip_frac: float = 0.1) -> dict:
    im = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    h, w, _ = im.shape
    sw = max(8, int(round(w * strip_frac)))
    left = im[:, :sw]
    right = im[:, -sw:]
    # Also compare left to right-shifted positions
    best = None
    for off in range(0, w - sw + 1, 2):
        ref = im[:, off : off + sw]
        err = float(np.mean((left - ref) ** 2))
        if best is None or err < best[0]:
            best = (err, off)
    # Continuity across seam at sw: difference between col sw-1 and sw
    seam = float(np.mean(np.abs(im[:, sw] - im[:, sw - 1])))
    # Continuity mid-frame
    mid = w // 2
    midc = float(np.mean(np.abs(im[:, mid] - im[:, mid - 1])))
    return {
        "file": path.name,
        "w": w,
        "strip": sw,
        "left_vs_right_mse": float(np.mean((left - right) ** 2)),
        "left_best_match_x": best[1],
        "left_best_mse": best[0],
        "seam_delta": seam,
        "mid_delta": midc,
        "seam_ratio": seam / max(midc, 1e-6),
    }


def main():
    files = sorted(OUT.glob("crop_x*.jpg")) + sorted(OUT.glob("crop_full*.jpg"))
    rows = [score(p) for p in files if p.exists()]
    rows.sort(key=lambda r: r["seam_ratio"], reverse=True)
    for r in rows:
        print(
            f"{r['file']:18} seam_ratio={r['seam_ratio']:.2f} "
            f"seam={r['seam_delta']:.1f} mid={r['mid_delta']:.1f} "
            f"left~x{r['left_best_match_x']}(mse={r['left_best_mse']:.0f}) "
            f"LvsR={r['left_vs_right_mse']:.0f}"
        )
    # Suggest crop that minimizes seam_ratio
    if rows:
        best = min(rows, key=lambda r: r["seam_ratio"])
        print("BEST_CONTINUITY", best["file"], "seam_ratio", round(best["seam_ratio"], 2))


if __name__ == "__main__":
    main()
