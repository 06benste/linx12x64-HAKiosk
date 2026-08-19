#!/usr/bin/env python3
"""Approved Linx front-camera preview look (post-ISP software grade)."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "camera_preview.json"


@dataclass
class PreviewLook:
    exposure_ev: float = -0.034
    contrast: float = 1.021
    saturation: float = 1.080
    wb_r: float = 1.348
    wb_g: float = 0.910
    wb_b: float = 1.001
    # shadows > 0 lifts darks; highlights > 0 recovers/compresses brights
    shadows: float = 0.0
    highlights: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreviewLook":
        sp = data.get("software_preview", data)
        return cls(
            exposure_ev=float(sp.get("exposure_ev", cls.exposure_ev)),
            contrast=float(sp.get("contrast", cls.contrast)),
            saturation=float(sp.get("saturation", cls.saturation)),
            wb_r=float(sp.get("wb_r", cls.wb_r)),
            wb_g=float(sp.get("wb_g", cls.wb_g)),
            wb_b=float(sp.get("wb_b", cls.wb_b)),
            shadows=float(sp.get("shadows", cls.shadows)),
            highlights=float(sp.get("highlights", cls.highlights)),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "PreviewLook":
        p = path or DEFAULT_CONFIG
        if p.exists():
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        return cls()

    def to_software_dict(self) -> dict[str, float]:
        return {
            "exposure_ev": round(self.exposure_ev, 4),
            "contrast": round(self.contrast, 4),
            "saturation": round(self.saturation, 4),
            "wb_r": round(self.wb_r, 4),
            "wb_g": round(self.wb_g, 4),
            "wb_b": round(self.wb_b, 4),
            "shadows": round(self.shadows, 4),
            "highlights": round(self.highlights, 4),
        }

    def ffmpeg_filter(self, *, crop: bool = True) -> str:
        """Build an ffmpeg -vf chain approximating this look (no S/H curve)."""
        parts: list[str] = []
        if crop:
            parts.append("crop=1584:1184:0:0")
        parts.append(
            "colorchannelmixer="
            f"rr={self.wb_r:.4f}:gg={self.wb_g:.4f}:bb={self.wb_b:.4f}"
        )
        bright = (2.0**self.exposure_ev) - 1.0
        parts.append(
            "eq="
            f"contrast={self.contrast:.4f}:"
            f"saturation={self.saturation:.4f}:"
            f"brightness={bright:.4f}"
        )
        return ",".join(parts)


@dataclass
class AutoSettings:
    """Software 3A (AtomISP hardware AWB/AE is broken/unusable on this tablet)."""

    enabled: bool = True
    target_luma: float = 100.0
    target_span: float = 125.0
    luma_smooth: float = 0.18
    wb_smooth: float = 0.08
    contrast_smooth: float = 0.10
    min_ev: float = -1.0
    max_ev: float = 2.2
    min_wb: float = 0.75
    max_wb: float = 1.55
    min_contrast: float = 0.90
    max_contrast: float = 1.40

    @classmethod
    def from_config(cls, path: Path | None = None) -> "AutoSettings":
        p = path or DEFAULT_CONFIG
        cfg: dict[str, Any] = {}
        if p.exists():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8")).get("auto", {}) or {}
            except Exception:
                cfg = {}
        return cls(
            enabled=bool(cfg.get("enabled", cls.enabled)),
            target_luma=float(cfg.get("target_luma", cls.target_luma)),
            target_span=float(cfg.get("target_span", cls.target_span)),
            luma_smooth=float(cfg.get("luma_smooth", cls.luma_smooth)),
            wb_smooth=float(cfg.get("wb_smooth", cls.wb_smooth)),
            contrast_smooth=float(cfg.get("contrast_smooth", cls.contrast_smooth)),
            min_ev=float(cfg.get("min_ev", cls.min_ev)),
            max_ev=float(cfg.get("max_ev", cls.max_ev)),
            min_wb=float(cfg.get("min_wb", cls.min_wb)),
            max_wb=float(cfg.get("max_wb", cls.max_wb)),
            min_contrast=float(cfg.get("min_contrast", cls.min_contrast)),
            max_contrast=float(cfg.get("max_contrast", cls.max_contrast)),
        )


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _tone_lut(shadows: float, highlights: float) -> list[int]:
    """Per-channel LUT: lift shadows / compress highlights."""
    lut: list[int] = []
    for i in range(256):
        x = i / 255.0
        y = x + float(shadows) * ((1.0 - x) ** 2) - float(highlights) * (x**2)
        lut.append(max(0, min(255, int(round(y * 255.0)))))
    return lut


def apply_preview(img: Image.Image, look: PreviewLook | None = None) -> Image.Image:
    look = look or PreviewLook.load()
    out = img.convert("RGB")
    mult = 2.0 ** float(look.exposure_ev)
    if abs(mult - 1.0) > 1e-4:
        out = ImageEnhance.Brightness(out).enhance(mult)
    if abs(look.contrast - 1.0) > 1e-4:
        out = ImageEnhance.Contrast(out).enhance(look.contrast)
    if abs(look.saturation - 1.0) > 1e-4:
        out = ImageEnhance.Color(out).enhance(look.saturation)
    if any(abs(x - 1.0) > 1e-4 for x in (look.wb_r, look.wb_g, look.wb_b)):
        r, g, b = out.split()
        r = r.point(lambda p, m=look.wb_r: min(255, int(p * m)))
        g = g.point(lambda p, m=look.wb_g: min(255, int(p * m)))
        b = b.point(lambda p, m=look.wb_b: min(255, int(p * m)))
        out = Image.merge("RGB", (r, g, b))
    if abs(look.shadows) > 1e-4 or abs(look.highlights) > 1e-4:
        out = out.point(_tone_lut(look.shadows, look.highlights) * 3)
    return out


class AutoLookState:
    """EMA-smoothed auto brightness / contrast / white-balance."""

    def __init__(self) -> None:
        self.ev = 0.0
        self.wb_r = 1.0
        self.wb_g = 1.0
        self.wb_b = 1.0
        self.contrast = 1.0
        self._primed = False
        self.last_stats: dict[str, float] = {}

    def reset(self) -> None:
        self.ev = 0.0
        self.wb_r = 1.0
        self.wb_g = 1.0
        self.wb_b = 1.0
        self.contrast = 1.0
        self._primed = False
        self.last_stats = {}

    def update(
        self,
        img: Image.Image,
        base: PreviewLook,
        auto: AutoSettings | None = None,
    ) -> PreviewLook:
        auto = auto or AutoSettings()
        if not auto.enabled:
            return base

        # Keep AtomISP teal correction / tuned look as the floor; auto only
        # nudges EV / relative WB / contrast around that base.
        if not self._primed:
            self.ev = float(base.exposure_ev)
            self.wb_r = float(base.wb_r)
            self.wb_g = float(base.wb_g)
            self.wb_b = float(base.wb_b)
            self.contrast = float(base.contrast)

        small = img.convert("RGB").resize((160, 120), Image.Resampling.BILINEAR)
        pixels = list(small.getdata())
        n = max(1, len(pixels))
        w, h = small.size

        # Midtone / non-clipped samples — ignore blown lamps for AE/AWB.
        # Prefer the centre (face / subject) over the ceiling lamp band.
        mid: list[tuple[int, int, int]] = []
        lumas_all: list[float] = []
        center_lumas: list[float] = []
        for idx, (r, g, b) in enumerate(pixels):
            y = 0.2126 * r + 0.7152 * g + 0.0722 * b
            lumas_all.append(y)
            x = idx % w
            yy = idx // w
            # Centre 50% width x lower 70% (skip top lamp band).
            if 0.25 * w <= x <= 0.75 * w and 0.30 * h <= yy <= 0.95 * h:
                center_lumas.append(y)
                if 16.0 <= y <= 215.0:
                    mid.append((r, g, b))
            elif 22.0 <= y <= 210.0 and len(mid) < 80:
                mid.append((r, g, b))
        sample = mid if len(mid) >= max(20, n // 12) else pixels
        sn = max(1, len(sample))
        sr = sum(p[0] for p in sample) / sn
        sg = sum(p[1] for p in sample) / sn
        sb = sum(p[2] for p in sample) / sn
        luma = 0.2126 * sr + 0.7152 * sg + 0.0722 * sb
        # Prefer median of centre band for exposure under bright lamps.
        lumas_all.sort()
        meter_src = sorted(center_lumas) if len(center_lumas) >= 30 else lumas_all
        median = meter_src[len(meter_src) // 2]
        p95 = lumas_all[int(0.95 * (len(lumas_all) - 1))]
        meter = 0.75 * median + 0.25 * luma

        # Exposure: aim for target mean luma after 2^ev gain.
        # Huge DR (ceiling lamp) → mild cap only; shadows curve lifts the face.
        safe_luma = max(meter, 2.0)
        desired_ev = math.log2(auto.target_luma / safe_luma)
        max_ev = auto.max_ev
        if p95 >= 220.0 and (p95 - median) >= 140.0:
            max_ev = min(max_ev, 1.55)
        desired_ev = _clamp(desired_ev, auto.min_ev, max_ev)

        # Gray-world *relative* to the approved base WB (not absolute 1.0).
        gray = (sr + sg + sb) / 3.0
        wr = gray / max(sr, 1.0)
        wg = gray / max(sg, 1.0)
        wb = gray / max(sb, 1.0)
        gmean = max((wr * wg * wb) ** (1.0 / 3.0), 1e-6)
        wr, wg, wb = wr / gmean, wg / gmean, wb / gmean
        # Narrow relative nudge (±~15%) around base AtomISP correction.
        wr = _clamp(float(base.wb_r) * wr, float(base.wb_r) * auto.min_wb, float(base.wb_r) * auto.max_wb)
        wg = _clamp(float(base.wb_g) * wg, float(base.wb_g) * auto.min_wb, float(base.wb_g) * auto.max_wb)
        wb = _clamp(float(base.wb_b) * wb, float(base.wb_b) * auto.min_wb, float(base.wb_b) * auto.max_wb)
        # Also hard-clamp absolute channel gains.
        wr = _clamp(wr, 0.70, 1.70)
        wg = _clamp(wg, 0.70, 1.40)
        wb = _clamp(wb, 0.70, 1.60)

        # Contrast from mid-tone span (p10..p90), relative to base.
        lumas = sorted(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in sample)
        sn2 = max(1, len(lumas))
        p10 = lumas[int(0.10 * (sn2 - 1))]
        p90 = lumas[int(0.90 * (sn2 - 1))]
        span = max(p90 - p10, 10.0)
        desired_c = _clamp(
            float(base.contrast) * (auto.target_span / span),
            auto.min_contrast,
            auto.max_contrast,
        )

        a_ev = 1.0 if not self._primed else auto.luma_smooth
        a_wb = 1.0 if not self._primed else auto.wb_smooth
        a_c = 1.0 if not self._primed else auto.contrast_smooth
        self.ev = (1.0 - a_ev) * self.ev + a_ev * desired_ev
        self.wb_r = (1.0 - a_wb) * self.wb_r + a_wb * wr
        self.wb_g = (1.0 - a_wb) * self.wb_g + a_wb * wg
        self.wb_b = (1.0 - a_wb) * self.wb_b + a_wb * wb
        self.contrast = (1.0 - a_c) * self.contrast + a_c * desired_c
        self._primed = True

        self.last_stats = {
            "luma": round(luma, 1),
            "meter": round(meter, 1),
            "median": round(median, 1),
            "p95": round(p95, 1),
            "span": round(span, 1),
            "ev": round(self.ev, 3),
            "contrast": round(self.contrast, 3),
            "wb_r": round(self.wb_r, 3),
            "wb_g": round(self.wb_g, 3),
            "wb_b": round(self.wb_b, 3),
        }

        # Keep artistic saturation / tone curve from the approved look;
        # auto owns exposure, contrast, and WB nudges around that base.
        return PreviewLook(
            exposure_ev=self.ev,
            contrast=self.contrast,
            saturation=base.saturation,
            wb_r=self.wb_r,
            wb_g=self.wb_g,
            wb_b=self.wb_b,
            shadows=base.shadows,
            highlights=base.highlights,
        )
