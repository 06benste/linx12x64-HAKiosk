#!/usr/bin/env python3
"""
MJPEG live stream for Linx AtomISP front camera.

Critical: AtomISP NV12 buffers are 1584x1184 with bytesperline=1600
(Size Image = 2842624). Feeding a raw byte pipe without frame alignment
causes rolling/shearing and chroma garbage. This server:

  v4l2-ctl --stream-to=-  ->  Python reads EXACT frames  ->  ffmpeg  ->  MJPEG clients

Also serves a local camera look tuner at /tuner and /api/look.
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Ensure /opt/ha-kiosk/scripts (or repo scripts/) is importable when run as a file.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    from gc2355_hw_exposure import HwExposureKeeper, apply_profile as apply_hw_exposure
except ImportError:  # pragma: no cover
    HwExposureKeeper = None  # type: ignore[misc, assignment]

    def apply_hw_exposure(*_a, **_k):  # type: ignore[misc]
        return {"ok": False, "error": "gc2355_hw_exposure missing"}

INSTALL = pathlib.Path("/opt/ha-kiosk")
# Repo / local-dev fallback: scripts/ next to this file -> ../config
_LOCAL_ROOT = pathlib.Path(__file__).resolve().parents[1]
CFG = pathlib.Path(
    os.environ.get(
        "CAMERA_PREVIEW_JSON",
        str(
            INSTALL / "config" / "camera_preview.json"
            if (INSTALL / "config" / "camera_preview.json").exists()
            else _LOCAL_ROOT / "config" / "camera_preview.json"
        ),
    )
)
STATIC_DIR = pathlib.Path(
    os.environ.get(
        "CAMERA_TUNER_STATIC",
        str(
            INSTALL / "scripts" / "static"
            if (INSTALL / "scripts" / "static" / "cam-tuner.html").exists()
            else pathlib.Path(__file__).resolve().parent / "static"
        ),
    )
)
HOST = os.environ.get("CAMERA_STREAM_HOST", "0.0.0.0")
PORT = int(os.environ.get("CAMERA_STREAM_PORT", "17824"))
# Shares power-api.py's token by default (same file, same LAN, one secret to
# hand to Home Assistant instead of two) — CAMERA_STREAM_TOKEN overrides it
# for this service specifically if you ever want them to differ.
_TOKEN_FILE = pathlib.Path("/opt/ha-kiosk/api.token")
TOKEN = os.environ.get("CAMERA_STREAM_TOKEN", "").strip()
if not TOKEN and _TOKEN_FILE.exists():
    TOKEN = _TOKEN_FILE.read_text(encoding="utf-8").strip()
WIDTH = int(os.environ.get("CAMERA_STREAM_WIDTH", "800"))
HEIGHT = int(os.environ.get("CAMERA_STREAM_HEIGHT", "600"))
FPS = int(os.environ.get("CAMERA_STREAM_FPS", "15"))
QUALITY = int(os.environ.get("CAMERA_STREAM_QUALITY", "6"))
TIMECODE = os.environ.get("CAMERA_STREAM_TIMECODE", "1").strip() not in ("0", "false", "False", "no")
V4L_BUFFERS = max(2, min(8, int(os.environ.get("CAMERA_STREAM_V4L_BUFFERS", "4"))))
# AtomISP/CSS delivers this sensor's frames with a horizontal line-buffer
# wrap: the leftmost strip of the output actually belongs at the right
# edge, showing up as a duplicated/discontinuous sliver at the left border
# instead of one contiguous scene. Confirmed empirically on real hardware
# (not documented anywhere upstream). The exact pixel width isn't a fixed
# hardware constant we can trust long-term — it was ~60px in an old
# reference session and measured at ~17-25px on this project's current
# capture (column-to-column brightness discontinuity, see scratch analysis
# in project history); re-measure with a plain/uncorrected capture
# (CAMERA_STREAM_WRAP_PX=0) if the seam ever reappears at the wrong offset.
WRAP_STRIP_PX = max(0, int(os.environ.get("CAMERA_STREAM_WRAP_PX", "22")))
# Restart capture if no JPEG for this long while clients are connected.
STALL_S = float(os.environ.get("CAMERA_STREAM_STALL_S", "8"))
WATCHDOG_EVERY_S = float(os.environ.get("CAMERA_STREAM_WATCHDOG_S", "2"))
PLAIN_FIFO = pathlib.Path(os.environ.get("CAMERA_PLAIN_FIFO", "/tmp/ha-kiosk-cam-plain.mjpeg"))
INPUT_FILE = pathlib.Path(
    os.environ.get("CAMERA_INPUT_FILE", str(INSTALL / "config" / "camera_input"))
)
INPUT_NAMES = {0: "front", 1: "rear"}


def load_camera_input() -> int:
    env = os.environ.get("CAMERA_STREAM_INPUT", "").strip()
    if env.isdigit():
        return 0 if int(env) <= 0 else 1
    if env.lower() in ("rear", "back"):
        return 1
    if env.lower() in ("front",):
        return 0
    try:
        raw = INPUT_FILE.read_text(encoding="utf-8").strip().lower()
        if raw in ("1", "rear", "back"):
            return 1
        if raw.isdigit():
            return 0 if int(raw) <= 0 else 1
    except Exception:
        pass
    return 0


def save_camera_input(inp: int) -> None:
    inp = 0 if int(inp) <= 0 else 1
    INPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    INPUT_FILE.write_text(f"{inp}\n", encoding="utf-8")

FRAME_W = 1600
FRAME_H = 1184
NV12_PAYLOAD = FRAME_W * FRAME_H * 3 // 2
FRAME_SIZE = int(os.environ.get("CAMERA_FRAME_SIZE", "2842624"))
CROP_W = 1584
CROP_H = 1184

LOOK_KEYS = (
    "exposure_ev",
    "contrast",
    "saturation",
    "wb_r",
    "wb_g",
    "wb_b",
    "shadows",
    "highlights",
)
LOOK_LIMITS = {
    "exposure_ev": (-1.5, 2.5),
    "contrast": (0.5, 2.0),
    "saturation": (0.0, 2.5),
    "wb_r": (0.5, 2.0),
    "wb_g": (0.5, 2.0),
    "wb_b": (0.5, 2.0),
    "shadows": (0.0, 0.7),
    "highlights": (0.0, 0.5),
}
DEFAULT_LOOK: dict[str, float] = {
    "wb_r": 1.348,
    "wb_g": 0.910,
    "wb_b": 1.001,
    "contrast": 1.021,
    "saturation": 1.080,
    "exposure_ev": -0.034,
    "shadows": 0.0,
    "highlights": 0.0,
}


def normalize_facing(inp: int | str | None = None) -> str:
    """Map input index / facing name to 'front' or 'rear'."""
    if inp is None:
        return INPUT_NAMES.get(load_camera_input(), "front")
    if isinstance(inp, str):
        key = inp.strip().lower()
        if key in ("rear", "back", "1"):
            return "rear"
        if key in ("front", "0"):
            return "front"
        return INPUT_NAMES.get(load_camera_input(), "front")
    return INPUT_NAMES.get(0 if int(inp) <= 0 else 1, "front")


def _look_from_mapping(sp: dict | None) -> dict[str, float]:
    look = dict(DEFAULT_LOOK)
    if isinstance(sp, dict):
        for k in LOOK_KEYS:
            if k in sp:
                try:
                    look[k] = float(sp[k])
                except (TypeError, ValueError):
                    pass
    return look


def load_look(inp: int | str | None = None) -> dict[str, float]:
    """Load software look for a facing (defaults to active camera).

    Config layout:
      software_preview              — legacy / front look
      software_preview_by_facing    — { front: {...}, rear: {...} }
    Rear falls back to front look until saved separately.
    """
    facing = normalize_facing(inp)
    look = dict(DEFAULT_LOOK)
    try:
        data = json.loads(CFG.read_text(encoding="utf-8"))
        by = data.get("software_preview_by_facing")
        if not isinstance(by, dict):
            by = {}
        legacy = data.get("software_preview")
        front = by.get("front") if isinstance(by.get("front"), dict) else legacy
        rear = by.get("rear") if isinstance(by.get("rear"), dict) else None
        chosen = rear if facing == "rear" and rear else front
        look = _look_from_mapping(chosen if isinstance(chosen, dict) else None)
    except Exception:
        pass
    return look


def clamp_look(raw: dict, fallback: dict[str, float] | None = None) -> dict[str, float]:
    base = fallback or DEFAULT_LOOK
    out: dict[str, float] = {}
    for k in LOOK_KEYS:
        lo, hi = LOOK_LIMITS[k]
        default = float(
            base.get(
                k,
                1.0 if k.startswith("wb") or k in ("contrast", "saturation") else 0.0,
            )
        )
        v = float(raw.get(k, default))
        out[k] = max(lo, min(hi, v))
    return out


def save_look(look: dict[str, float], inp: int | str | None = None) -> dict:
    """Merge per-facing software look into config JSON; preserve auto/capture."""
    facing = normalize_facing(inp)
    CFG.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if CFG.exists():
        try:
            data = json.loads(CFG.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["version"] = int(data.get("version") or 1)
    data["approved_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    rounded = {k: round(float(look[k]), 4) for k in LOOK_KEYS}
    by = data.get("software_preview_by_facing")
    if not isinstance(by, dict):
        by = {}
    # Seed front from legacy flat software_preview if missing.
    if "front" not in by and isinstance(data.get("software_preview"), dict):
        by["front"] = {
            k: round(float(data["software_preview"][k]), 4)
            for k in LOOK_KEYS
            if k in data["software_preview"]
        }
    by[facing] = rounded
    data["software_preview_by_facing"] = by
    # Keep legacy software_preview mirrored to front for older readers.
    data["software_preview"] = dict(by.get("front") or rounded)
    data.setdefault("notes", "Updated via on-tablet camera tuner")
    tmp = CFG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CFG)
    return data


def build_grade_filters(look: dict[str, float]) -> str:
    """Grade + optional timecode (no crop/scale)."""
    parts: list[str] = []
    mult = 2.0 ** float(look["exposure_ev"])
    if abs(mult - 1.0) > 1e-3:
        parts.append(
            "lutrgb="
            f"r='min(val*{mult:.4f}\\,255)':"
            f"g='min(val*{mult:.4f}\\,255)':"
            f"b='min(val*{mult:.4f}\\,255)'"
        )
    parts.append(
        "colorchannelmixer="
        f"rr={look['wb_r']:.4f}:gg={look['wb_g']:.4f}:bb={look['wb_b']:.4f}"
    )
    shadows = float(look.get("shadows", 0.0) or 0.0)
    # Mild gamma + optional additive floor; heavy black lift via curves below.
    gamma = max(0.62, 1.0 - 0.40 * shadows) if shadows > 0.01 else 1.0
    bright = min(0.12, 0.18 * shadows) if shadows > 0.01 else 0.0
    parts.append(
        "eq="
        f"contrast={look['contrast']:.4f}:"
        f"saturation={look['saturation']:.4f}:"
        f"brightness={bright:.3f}:"
        f"gamma={gamma:.3f}"
    )
    if shadows > 0.01:
        # Lift crushed indoor blacks without blowing the whole frame (backlit faces).
        y0 = min(0.28, 0.06 + 0.35 * shadows)
        y25 = min(0.52, 0.28 + 0.35 * shadows)
        y50 = min(0.62, 0.50 + 0.12 * shadows)
        parts.append(f"curves=all='0/{y0:.3f} 0.25/{y25:.3f} 0.5/{y50:.3f} 1/1'")
    highlights = float(look.get("highlights", 0.0) or 0.0)
    if highlights > 0.01:
        thr = int(max(150, 230 - 90 * highlights))
        soft = max(0.25, 1.0 - 1.1 * highlights)
        parts.append(
            "lutrgb="
            f"r='if(lt(val\\,{thr})\\,val\\,{thr}+(val-{thr})*{soft:.3f})':"
            f"g='if(lt(val\\,{thr})\\,val\\,{thr}+(val-{thr})*{soft:.3f})':"
            f"b='if(lt(val\\,{thr})\\,val\\,{thr}+(val-{thr})*{soft:.3f})'"
        )
    if TIMECODE:
        font_candidates = (
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        )
        font = next((p for p in font_candidates if pathlib.Path(p).exists()), "")
        if font:
            parts.append(
                "drawtext="
                f"fontfile={font}:"
                r"text='%{localtime\:%H\\\:%M\\\:%S}':"
                "x=(w-text_w)/2:y=h/40:"
                "fontsize=h/22:fontcolor=white:borderw=2:bordercolor=black"
            )
    return ",".join(parts)


WRAP_OUT_PAD = "[out]"


def build_stream_filtergraph(look: dict[str, float]) -> str:
    """Crop/scale + wrap-seam correction + grade + timecode, as an ffmpeg
    filter_complex graph (needs -filter_complex/-map "[out]", not -vf —
    the wrap fix needs split/hstack, which plain -vf can't express).

    See WRAP_STRIP_PX above for what the wrap correction is fixing.
    """
    # WRAP_STRIP_PX is specified in 800-wide output-scale pixels (that's
    # the domain it was measured in), but the cut itself must happen on
    # the native 1584-wide crop, BEFORE the downscale to WIDTH — scaling
    # first bilinear-blends pixels across the true wrap boundary, which
    # leaves a faint residual seam on both output edges that no amount of
    # cutting after the fact can undo (confirmed on real hardware: cutting
    # post-scale left exactly this symptom). Cut on the source resolution,
    # then scale the already-corrected frame down.
    strip = round(WRAP_STRIP_PX * CROP_W / WIDTH) if WRAP_STRIP_PX > 0 else 0
    if strip <= 0 or strip >= CROP_W:
        # Disabled (or nonsensical) — plain crop/scale, still via
        # filter_complex so callers don't need two code paths.
        graph = f"crop={CROP_W}:{CROP_H}:0:0,scale={WIDTH}:{HEIGHT}:flags=fast_bilinear[wrapped]"
    else:
        main_w = CROP_W - strip
        graph = (
            f"crop={CROP_W}:{CROP_H}:0:0,split=2[s0][s1];"
            f"[s0]crop={main_w}:{CROP_H}:{strip}:0[main];"
            f"[s1]crop={strip}:{CROP_H}:0:0[strip];"
            f"[main][strip]hstack=inputs=2,scale={WIDTH}:{HEIGHT}:flags=fast_bilinear[wrapped]"
        )
    grade = build_grade_filters(look)
    tail = f"[wrapped]{grade}{WRAP_OUT_PAD}" if grade else f"[wrapped]null{WRAP_OUT_PAD}"
    return f"{graph};{tail}"


def _graceful_pkill(pattern: str, grace_s: float = 0.5) -> None:
    """SIGINT first, SIGKILL only as a fallback. v4l2-ctl's --stream-* loop
    is designed to be interrupted with Ctrl+C (SIGINT) — that's what lets it
    call VIDIOC_STREAMOFF and release the ISP cleanly. Going straight to
    SIGKILL mid-ioctl is a plausible way to leave the AtomISP driver wedged
    in an uninterruptible D-state (unkillable by any signal, including this
    same SIGKILL) — which has been observed to hang tablet shutdown for
    minutes waiting on a process that can never die. This costs at most
    grace_s extra, only when something was actually still running.
    """
    subprocess.run(["pkill", "-INT", "-f", pattern], check=False)
    time.sleep(grace_s)
    subprocess.run(["pkill", "-9", "-f", pattern], check=False)


def read_exact(stream, size: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < size:
        chunk = stream.read(size - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _parse_mjpeg_loop(read_fn, on_frame, stop_event: threading.Event, label: str) -> None:
    buf = b""
    try:
        while not stop_event.is_set():
            chunk = read_fn(4096)
            if not chunk:
                break
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")
                if start < 0:
                    buf = buf[-1:] if buf else b""
                    break
                if start > 0:
                    buf = buf[start:]
                    start = 0
                end = buf.find(b"\xff\xd9", 2)
                if end < 0:
                    break
                jpeg = buf[: end + 2]
                buf = buf[end + 2 :]
                if len(jpeg) >= 800:
                    on_frame(jpeg)
    except Exception as exc:  # noqa: BLE001
        print(f"{label} exit: {exc}", flush=True)
    finally:
        print(f"{label} exit", flush=True)


class FrameBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._frame: bytes | None = None  # graded
        self._frame_plain: bytes | None = None
        self._frame_id = 0
        self._clients = 0
        self._idle_gen = 0
        self._v4l: subprocess.Popen[bytes] | None = None
        self._ff: subprocess.Popen[bytes] | None = None
        self._plain_fh = None
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._started = 0.0
        self._frames_ok = 0
        self._last_error = ""
        self._start_lock = threading.Lock()
        self._hw_exp_last: dict = {}
        self._hw_keeper = None
        self._input = load_camera_input()
        self._look = load_look(self._input)
        self._last_frame_mono = 0.0
        self._restarts = 0
        self._watchdog_started = False
        self._starting = False

    def ensure_watchdog(self) -> None:
        if self._watchdog_started:
            return
        self._watchdog_started = True
        threading.Thread(target=self._watchdog_loop, name="cam-watchdog", daemon=True).start()

    def status(self) -> dict:
        with self._lock:
            alive = (
                self._v4l is not None
                and self._v4l.poll() is None
                and self._ff is not None
                and self._ff.poll() is None
            )
            age = (
                round(time.monotonic() - self._last_frame_mono, 1)
                if self._last_frame_mono
                else None
            )
            return {
                "ok": True,
                "streaming": alive,
                "clients": self._clients,
                "frames": self._frames_ok,
                "last_error": self._last_error,
                "last_frame_age_s": age,
                "restarts": self._restarts,
                "uptime_s": round(time.time() - self._started, 1) if self._started else 0,
                "size": f"{WIDTH}x{HEIGHT}",
                "fps": FPS,
                "frame_size": FRAME_SIZE,
                "look": dict(self._look),
                "input": int(self._input),
                "facing": INPUT_NAMES.get(int(self._input), "front"),
                "hw_exposure": dict(
                    (self._hw_keeper.last if self._hw_keeper is not None else self._hw_exp_last)
                    or {}
                ),
            }

    def add_client(self) -> None:
        with self._lock:
            self._clients += 1
            need = self._clients == 1
        if need:
            self.start()

    def remove_client(self) -> None:
        with self._lock:
            self._clients = max(0, self._clients - 1)
            self._idle_gen += 1
            token = self._idle_gen
            need_stop = self._clients == 0
        if need_stop:
            threading.Timer(45.0, self._stop_if_idle, args=(token,)).start()

    def _stop_if_idle(self, token: int) -> None:
        with self._lock:
            idle = self._clients == 0 and token == self._idle_gen
        if idle:
            self.stop()

    def reload_look(self) -> None:
        """Reload config and restart capture so ffmpeg grade picks up new look."""
        with self._start_lock:
            with self._lock:
                clients = self._clients
            was_running = False
            with self._lock:
                was_running = self._ff is not None and self._ff.poll() is None
            if was_running:
                self.stop()
            self._look = load_look(self._input)
            if clients > 0 or was_running:
                # Keep stream alive for connected MJPEG / MQTT clients.
                with self._lock:
                    if self._clients < 1:
                        self._clients = 1
                self._start_unlocked()

    def start(self) -> None:
        self.ensure_watchdog()
        with self._start_lock:
            self._start_unlocked()

    def _watchdog_loop(self) -> None:
        """Restart capture when AtomISP/ffmpeg stalls (common after ISP FW_ASSERT)."""
        while True:
            time.sleep(max(1.0, WATCHDOG_EVERY_S))
            try:
                self._watchdog_tick()
            except Exception as exc:  # noqa: BLE001
                print(f"watchdog error: {exc}", flush=True)

    def _watchdog_tick(self) -> None:
        with self._lock:
            clients = self._clients
            started = self._started
            frames = self._frames_ok
            last_mono = self._last_frame_mono
            v4l, ff = self._v4l, self._ff
            starting = self._starting
        if clients < 1 or not started or starting:
            return
        alive = (
            v4l is not None
            and v4l.poll() is None
            and ff is not None
            and ff.poll() is None
        )
        now = time.monotonic()
        wall = time.time()
        uptime = wall - started
        # Give AtomISP a few seconds to produce the first frame after spawn.
        if uptime < max(STALL_S, 10.0) and frames == 0 and alive:
            return
        if last_mono:
            stalled = (now - last_mono) >= STALL_S
        else:
            stalled = uptime >= max(STALL_S, 12.0) and frames == 0
        # Only treat as dead after the spawn window — avoids fighting _start_unlocked.
        dead = (not alive) and uptime >= 4.0
        if not (stalled or dead):
            return
        reason = "dead procs" if dead and not stalled else "frame stall"
        print(
            f"watchdog restart ({reason}): clients={clients} frames={frames} "
            f"age={None if not last_mono else round(now - last_mono, 1)}s "
            f"alive={alive}",
            flush=True,
        )
        with self._start_lock:
            with self._lock:
                still_clients = self._clients
                if self._starting:
                    return
            if still_clients < 1:
                return
            self.stop()
            time.sleep(0.4)
            # Every 3rd recovery, nudge AtomISP modules (ISP FW_ASSERT recovery).
            reload_modules = self._restarts % 3 == 2
            if reload_modules:
                subprocess.run(
                    ["/opt/ha-kiosk/scripts/load-atomisp.sh"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.5)
            self._restarts += 1
            self._start_unlocked(reload_modules=False)

    def _start_unlocked(self, *, reload_modules: bool = False) -> None:
        with self._lock:
            if self._ff and self._ff.poll() is None:
                return
            self._starting = True
            self._stop.clear()
            self._look = load_look(self._input)
            self._last_error = ""
            self._started = time.time()
            self._frames_ok = 0
            self._last_frame_mono = 0.0

        try:
            self._start_pipeline(reload_modules=reload_modules)
        finally:
            with self._lock:
                self._starting = False

    def _start_pipeline(self, *, reload_modules: bool = False) -> None:
        # load-atomisp.sh takes ~5s; only run on cold recovery, never on facing switch.
        if reload_modules:
            subprocess.run(
                ["/opt/ha-kiosk/scripts/load-atomisp.sh"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        _graceful_pkill("v4l2-ctl --stream")
        subprocess.run(
            ["pkill", "-9", "-f", "ffmpeg.*rawvideo.*1600x1184"],
            check=False,
        )
        time.sleep(0.15 if not reload_modules else 0.35)
        # Avoid blocking v4l2-ctl -c here: when AtomISP is wedged it can enter
        # uninterruptible sleep (D-state) and leave zombie capture processes.
        # Select front (0) or rear (1) before streaming.
        subprocess.run(
            ["v4l2-ctl", "-d", "/dev/video0", f"--set-input={int(self._input)}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )

        filtergraph = build_stream_filtergraph(self._look)

        try:
            v4l = subprocess.Popen(
                [
                    "v4l2-ctl",
                    "-d",
                    "/dev/video0",
                    f"--set-input={int(self._input)}",
                    "--set-fmt-video=width=1600,height=1200,pixelformat=NV12",
                    f"--stream-mmap={V4L_BUFFERS}",
                    "--stream-count=0",
                    "--stream-to=-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            ff = subprocess.Popen(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-fflags",
                    "nobuffer",
                    "-flags",
                    "low_delay",
                    "-probesize",
                    "32",
                    "-analyzeduration",
                    "0",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "nv12",
                    "-video_size",
                    f"{FRAME_W}x{FRAME_H}",
                    "-framerate",
                    str(FPS),
                    "-i",
                    "pipe:0",
                    "-filter_complex",
                    filtergraph,
                    "-map",
                    WRAP_OUT_PAD,
                    "-an",
                    "-c:v",
                    "mjpeg",
                    "-q:v",
                    str(QUALITY),
                    "-f",
                    "mjpeg",
                    "pipe:1",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # Never PIPE stderr without a reader — fills and deadlocks ffmpeg.
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = str(exc)
            return

        with self._lock:
            self._v4l = v4l
            self._ff = ff
            self._plain_fh = None

        def on_frame(jpeg: bytes) -> None:
            with self._cond:
                self._frame = jpeg
                self._frame_plain = jpeg
                self._frame_id += 1
                self._frames_ok += 1
                self._last_frame_mono = time.monotonic()
                self._cond.notify_all()

        t1 = threading.Thread(target=self._pump_frames, args=(v4l, ff), daemon=True)
        t2 = threading.Thread(
            target=_parse_mjpeg_loop,
            args=(ff.stdout.read, on_frame, self._stop, "jpeg reader"),
            daemon=True,
        )
        self._threads = [t1, t2]
        t1.start()
        t2.start()
        if HwExposureKeeper is not None:
            keeper = HwExposureKeeper(
                self._stop,
                # Avoid hammering i2c while ISP is streaming (can trip FW_ASSERT).
                interval_s=8.0,
                input_getter=lambda: self._input,
            )
            self._hw_keeper = keeper
            self._threads.append(keeper)
            keeper.start()
        else:
            self._hw_keeper = None
        print(
            f"camera stream started v4l={v4l.pid} ff={ff.pid} "
            f"{WIDTH}x{HEIGHT}@{FPS} input={self._input}/{INPUT_NAMES.get(self._input, '?')} "
            f"frame={FRAME_SIZE}",
            flush=True,
        )

    def set_input(self, inp: int | str) -> dict:
        """Switch front/rear camera (restarts capture if clients are connected)."""
        if isinstance(inp, str):
            key = inp.strip().lower()
            if key in ("rear", "back", "1"):
                want = 1
            elif key in ("front", "0"):
                want = 0
            else:
                raise ValueError("input must be front/rear or 0/1")
        else:
            want = 0 if int(inp) <= 0 else 1
        with self._lock:
            cur = int(self._input)
            clients = self._clients
        if want == cur:
            return {
                "ok": True,
                "input": want,
                "facing": INPUT_NAMES[want],
                "restarted": False,
                "look": dict(self._look),
            }
        save_camera_input(want)
        with self._lock:
            self._input = want
            self._look = load_look(want)
        # Fast path: stop + restart without reloading AtomISP modules (~5s).
        t0 = time.monotonic()
        with self._start_lock:
            self.stop()
            if clients > 0:
                self._start_unlocked(reload_modules=False)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        print(
            f"camera input switch -> {want}/{INPUT_NAMES[want]} "
            f"clients={clients} in {elapsed_ms}ms",
            flush=True,
        )
        return {
            "ok": True,
            "input": want,
            "facing": INPUT_NAMES[want],
            "restarted": clients > 0,
            "elapsed_ms": elapsed_ms,
            "look": dict(self._look),
        }

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            v4l, ff = self._v4l, self._ff
            self._v4l = None
            self._ff = None
            self._plain_fh = None
            self._hw_keeper = None
        with self._cond:
            self._cond.notify_all()
        for proc in (ff, v4l):
            if not proc:
                continue
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            # SIGINT first (the signal v4l2-ctl's stream loop is designed to
            # unwind cleanly on, same as Ctrl+C) — SIGKILL mid-ioctl is a
            # plausible way to wedge the AtomISP driver into an unkillable
            # D-state. Short grace period, then fall back to SIGKILL.
            try:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=1.0)
                continue
            except Exception:
                pass
            try:
                proc.kill()
                proc.wait(timeout=0.6)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        _graceful_pkill("v4l2-ctl --stream")
        subprocess.run(
            ["pkill", "-9", "-f", "ffmpeg.*rawvideo.*1600x1184"],
            check=False,
        )
        print("camera stream stopped", flush=True)

    def _pump_frames(self, v4l: subprocess.Popen[bytes], ff: subprocess.Popen[bytes]) -> None:
        assert v4l.stdout and ff.stdin
        period = 1.0 / max(FPS, 1)
        next_t = 0.0
        try:
            while not self._stop.is_set() and v4l.poll() is None and ff.poll() is None:
                frame = read_exact(v4l.stdout, FRAME_SIZE)
                if frame is None:
                    break
                now = time.monotonic()
                if now < next_t:
                    continue
                next_t = now + period
                try:
                    ff.stdin.write(frame[:NV12_PAYLOAD])
                    ff.stdin.flush()
                except BrokenPipeError:
                    break
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = f"pump: {exc}"
        finally:
            try:
                ff.stdin.close()
            except Exception:
                pass
            print("frame pump exit", flush=True)

    def wait_frame(
        self, last_id: int, timeout: float = 5.0, *, plain: bool = False
    ) -> tuple[int, bytes] | None:
        deadline = time.time() + timeout
        with self._cond:
            while True:
                frame = self._frame_plain if plain else self._frame
                if self._frame_id > last_id and frame is not None:
                    return self._frame_id, frame
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=remaining)

    def latest(self, *, plain: bool = False) -> bytes | None:
        with self._lock:
            return self._frame_plain if plain else self._frame


BROKER = FrameBroker()


def authorized(handler: BaseHTTPRequestHandler) -> bool:
    # On-device callers (the drawer's overlay iframe, the Cameras tab, a
    # direct /tuner visit on the tablet's own screen) are always exempt —
    # none of that client-side JS sends a token, so without this check,
    # turning TOKEN on by default would 401 the entire on-device camera UI,
    # not just remote LAN access. Mirrors power-api.py's
    # _client_is_local()/_authorized() split.
    if handler.client_address[0] in ("127.0.0.1", "::1"):
        return True
    if not TOKEN:
        return True
    q = parse_qs(urlparse(handler.path).query)
    got = (q.get("token") or [""])[0]
    if got == TOKEN:
        return True
    auth = handler.headers.get("Authorization", "")
    return auth == f"Bearer {TOKEN}"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _deny(self) -> None:
        self.send_response(401)
        self._cors()
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"unauthorized")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/"):
            self._json(200, BROKER.status())
            return

        if path == "/tuner" or path == "/tuner/":
            self._tuner_page()
            return

        if path == "/api/look":
            if not authorized(self):
                self._deny()
                return
            qs = parse_qs(urlparse(self.path).query)
            facing_q = (qs.get("facing") or qs.get("camera") or [None])[0]
            facing = normalize_facing(facing_q if facing_q else BROKER._input)
            look = load_look(facing)
            meta = {}
            try:
                meta = json.loads(CFG.read_text(encoding="utf-8"))
            except Exception:
                pass
            by = meta.get("software_preview_by_facing")
            if not isinstance(by, dict):
                by = {}
            self._json(
                200,
                {
                    "ok": True,
                    "software_preview": look,
                    "facing": facing,
                    "input": 0 if facing == "front" else 1,
                    "looks": {
                        "front": load_look("front"),
                        "rear": load_look("rear"),
                    },
                    "approved_at": meta.get("approved_at"),
                    "notes": meta.get("notes"),
                    "path": str(CFG),
                    "has_rear_look": isinstance(by.get("rear"), dict),
                },
            )
            return

        if path == "/api/input":
            if not authorized(self):
                self._deny()
                return
            self._json(
                200,
                {
                    "ok": True,
                    "input": int(BROKER._input),
                    "facing": INPUT_NAMES.get(int(BROKER._input), "front"),
                    "look": dict(BROKER._look),
                    "options": [{"input": 0, "facing": "front"}, {"input": 1, "facing": "rear"}],
                },
            )
            return

        if not authorized(self):
            self._deny()
            return

        if path in ("/snapshot.jpg", "/snapshot"):
            self._snapshot()
            return
        if path in ("/stream.mjpg", "/stream.mjpeg", "/stream"):
            self._stream()
            return

        self.send_response(404)
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/input":
            if not authorized(self):
                self._deny()
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return
            want = body.get("facing", body.get("input", body.get("camera")))
            try:
                result = BROKER.set_input(want)
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"ok": False, "error": str(exc)})
                return
            self._json(200, result)
            return
        if path != "/api/look":
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        if not authorized(self):
            self._deny()
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "error": "invalid JSON"})
            return
        sp = body.get("software_preview") or body
        facing_raw = body.get("facing", body.get("camera", body.get("input")))
        facing = normalize_facing(facing_raw if facing_raw is not None else BROKER._input)
        try:
            look = clamp_look(sp, fallback=load_look(facing))
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"ok": False, "error": str(exc)})
            return
        try:
            saved = save_look(look, facing)
            # Only restart grade if we saved the active camera's look.
            if facing == INPUT_NAMES.get(int(BROKER._input), "front"):
                BROKER.reload_look()
            else:
                # Persist only; active stream keeps its facing look.
                pass
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"ok": False, "error": str(exc)})
            return
        by = saved.get("software_preview_by_facing") or {}
        self._json(
            200,
            {
                "ok": True,
                "message": f"{facing.capitalize()} look saved"
                + (
                    "; stream reloading"
                    if facing == INPUT_NAMES.get(int(BROKER._input), "front")
                    else ""
                ),
                "software_preview": by.get(facing) or look,
                "facing": facing,
                "input": 0 if facing == "front" else 1,
                "approved_at": saved.get("approved_at"),
            },
        )

    def _tuner_page(self) -> None:
        path = STATIC_DIR / "cam-tuner.html"
        if not path.exists():
            self._json(404, {"ok": False, "error": f"tuner missing: {path}"})
            return
        data = path.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _want_plain(self) -> bool:
        q = parse_qs(urlparse(self.path).query)
        return (q.get("plain") or ["0"])[0] in ("1", "true", "yes")

    def _snapshot(self) -> None:
        plain = self._want_plain()
        BROKER.add_client()
        try:
            # Prefer a recent cached frame so MQTT/HA polling does not serialize
            # on wait_frame for every request.
            age = BROKER.status().get("last_frame_age_s")
            frame = None
            if age is not None and age <= 1.0:
                frame = BROKER.latest(plain=plain)
            if not frame:
                got = BROKER.wait_frame(BROKER._frame_id, timeout=15.0, plain=plain)  # noqa: SLF001
                frame = got[1] if got else BROKER.latest(plain=plain)
            if not frame:
                self.send_response(503)
                self._cors()
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"no frame")
                return
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(frame)
        finally:
            BROKER.remove_client()

    def _stream(self) -> None:
        plain = self._want_plain()
        BROKER.add_client()
        boundary = b"frame"
        try:
            self.send_response(200)
            self._cors()
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=%s" % boundary.decode(),
            )
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            last_id = 0
            misses = 0
            while True:
                got = BROKER.wait_frame(last_id, timeout=5.0, plain=plain)
                if not got:
                    misses += 1
                    st = BROKER.status()
                    # Drop hung clients so MQTT/browser reconnects don't leak forever
                    # while AtomISP is stalled (streaming may still look "alive").
                    if not st.get("streaming") or misses >= 3:
                        break
                    continue
                misses = 0
                last_id, frame = got
                header = (
                    b"--"
                    + boundary
                    + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(frame)).encode()
                    + b"\r\n\r\n"
                )
                self.wfile.write(header)
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            BROKER.remove_client()


def main() -> None:
    subprocess.run(
        ["/opt/ha-kiosk/scripts/load-atomisp.sh"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)

    def _shutdown(*_args) -> None:
        BROKER.stop()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    print(f"camera MJPEG listening on http://{HOST}:{PORT}/stream.mjpg", flush=True)
    print(f"camera tuner at http://{HOST}:{PORT}/tuner", flush=True)
    BROKER.ensure_watchdog()
    httpd.serve_forever()


if __name__ == "__main__":
    main()
