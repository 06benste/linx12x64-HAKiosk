#!/usr/bin/env python3
"""
Linx HA kiosk camera tuner GUI (runs on your PC, drives the tablet over SSH).

Captures from /dev/video0 on the tablet, shows the frame, and lets you dial
exposure / white-balance style controls. Hardware V4L2 controls are applied
when available; RGB gains are also applied in software so you can always see
the effect and report values back.
"""
from __future__ import annotations

import io
import json
import sys
import threading
import time
import urllib.request
import tkinter as tk
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import paramiko
from PIL import Image, ImageOps, ImageTk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from camera_preview import PreviewLook, apply_preview  # noqa: E402

DEFAULT_HOST = "192.168.8.201"
DEFAULT_USER = "kioskuser"
DEFAULT_PASS = "kiosk"
REMOTE_RAW = "/tmp/cam_tuner.raw"
REMOTE_JPG = "/tmp/cam_tuner.jpg"
LOGS = ROOT / "logs"
CONFIG = ROOT / "config" / "camera_preview.json"
APPROVED = PreviewLook.load()
STREAM_PORT = 17824


@dataclass
class TunerSettings:
    # Software preview (always applied to displayed image)
    exposure_ev: float = APPROVED.exposure_ev
    contrast: float = APPROVED.contrast
    saturation: float = APPROVED.saturation
    wb_r: float = APPROVED.wb_r
    wb_g: float = APPROVED.wb_g
    wb_b: float = APPROVED.wb_b
    shadows: float = APPROVED.shadows
    highlights: float = APPROVED.highlights
    # Hardware / capture
    capture_count: int = 2
    # Optional V4L2 absolute exposure (None = leave alone)
    hw_exposure: int | None = None
    note: str = ""


class TabletCam:
    def __init__(self, host: str, user: str, password: str):
        self.host = host
        self.user = user
        self.password = password
        self._client: paramiko.SSHClient | None = None

    def connect(self) -> None:
        self.close()
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(
            self.host,
            username=self.user,
            password=self.password,
            timeout=12,
            allow_agent=False,
            look_for_keys=False,
        )
        self._client = c

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None

    def _sudo(self, script: str, timeout: int = 90) -> tuple[int, str]:
        assert self._client
        # Write script remotely to avoid quoting hell
        sftp = self._client.open_sftp()
        remote = f"/tmp/cam_tuner_{int(time.time() * 1000)}.sh"
        with sftp.file(remote, "w") as f:
            f.write("#!/bin/bash\nset -euo pipefail\n" + script.replace("\r\n", "\n"))
        sftp.chmod(remote, 0o755)
        sftp.close()
        _, stdout, _ = self._client.exec_command(
            f"echo {self.password} | sudo -S -p '' bash {remote}; ec=$?; rm -f {remote}; exit $ec",
            timeout=timeout,
            get_pty=True,
        )
        out = stdout.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out

    def ensure_camera(self) -> str:
        rc, out = self._sudo(
            r"""
/opt/ha-kiosk/scripts/load-atomisp.sh >/dev/null 2>&1 || true
sleep 1
ls -l /dev/video0 /dev/media0
v4l2-ctl -d /dev/video0 --all 2>/dev/null | head -n 80 || true
""",
            timeout=60,
        )
        if rc != 0 and "/dev/video0" not in out:
            raise RuntimeError(f"camera not ready:\n{out[-1500:]}")
        return out

    def list_controls(self) -> str:
        _, out = self._sudo("v4l2-ctl -d /dev/video0 --list-ctrls-menus 2>&1 || v4l2-ctl -d /dev/video0 --list-ctrls 2>&1")
        return out

    def set_ctrl(self, name: str, value: int | float) -> str:
        rc, out = self._sudo(f"v4l2-ctl -d /dev/video0 --set-ctrl={name}={value} 2>&1")
        if rc != 0:
            raise RuntimeError(out[-800:] or f"set-ctrl failed ({rc})")
        return out

    def capture_jpeg(self, settings: TunerSettings) -> bytes:
        # Native ISP output is typically 1584x1184 with bytesperline 1600 (NV12).
        count = max(1, min(int(settings.capture_count), 5))
        hw = ""
        if settings.hw_exposure is not None:
            hw = f"v4l2-ctl -d /dev/video0 --set-ctrl=exposure={settings.hw_exposure} 2>/dev/null || true\n"
            hw += f"v4l2-ctl -d /dev/video0 --set-ctrl=exposure_absolute={settings.hw_exposure} 2>/dev/null || true\n"
        script = f"""
pkill -9 -f 'v4l2-ctl' 2>/dev/null || true
# Don't kill the live stream ffmpeg unless doing a still grab — leave stream alone when possible
rm -f {REMOTE_RAW} {REMOTE_JPG}
{hw}
timeout -s KILL 25 v4l2-ctl -d /dev/video0 \\
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \\
  --stream-mmap=4 --stream-count={count} --stream-to={REMOTE_RAW} 2>&1 || true
SZ=$(stat -c%s {REMOTE_RAW} 2>/dev/null || echo 0)
echo "RAW_SIZE=$SZ"
if [[ "$SZ" -lt 100000 ]]; then
  echo "capture too small" >&2
  exit 2
fi
# Prefer native stride geometry
ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1600x1184 -i {REMOTE_RAW} \\
  -vf crop=1584:1184:0:0 -frames:v 1 -q:v 3 -update 1 {REMOTE_JPG} 2>/dev/null \\
|| ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1600x1200 -i {REMOTE_RAW} \\
  -frames:v 1 -q:v 3 -update 1 {REMOTE_JPG} 2>/dev/null
ls -la {REMOTE_JPG}
"""
        rc, out = self._sudo(script, timeout=90)
        if rc != 0:
            raise RuntimeError(f"capture failed:\n{out[-2000:]}")
        assert self._client
        sftp = self._client.open_sftp()
        try:
            with sftp.file(REMOTE_JPG, "rb") as f:
                data = f.read()
        finally:
            sftp.close()
        if len(data) < 1000:
            raise RuntimeError("JPEG empty")
        return data


def apply_software(img: Image.Image, s: TunerSettings) -> Image.Image:
    """Apply preview exposure / contrast / saturation / RGB white-balance / S-H."""
    look = PreviewLook(
        exposure_ev=s.exposure_ev,
        contrast=s.contrast,
        saturation=s.saturation,
        wb_r=s.wb_r,
        wb_g=s.wb_g,
        wb_b=s.wb_b,
        shadows=s.shadows,
        highlights=s.highlights,
    )
    return apply_preview(img, look)


class CamTunerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Linx camera tuner")
        self.geometry("1180x780")
        self.minsize(960, 640)

        self.cam = TabletCam(DEFAULT_HOST, DEFAULT_USER, DEFAULT_PASS)
        self.settings = TunerSettings()
        self._raw_img: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._busy = False
        self._ctrl_vars: dict[str, tk.Variable] = {}
        self._live = False
        self._live_thread: threading.Thread | None = None

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        LOGS.mkdir(parents=True, exist_ok=True)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)

        # Connection row
        conn = ttk.LabelFrame(root, text="Tablet", padding=6)
        conn.pack(fill=tk.X)
        self.host_v = tk.StringVar(value=DEFAULT_HOST)
        self.user_v = tk.StringVar(value=DEFAULT_USER)
        self.pass_v = tk.StringVar(value=DEFAULT_PASS)
        ttk.Label(conn, text="Host").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(conn, textvariable=self.host_v, width=18).grid(row=0, column=1, padx=4)
        ttk.Label(conn, text="User").grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(conn, textvariable=self.user_v, width=12).grid(row=0, column=3, padx=4)
        ttk.Label(conn, text="Pass").grid(row=0, column=4, sticky=tk.W)
        ttk.Entry(conn, textvariable=self.pass_v, width=12, show="*").grid(row=0, column=5, padx=4)
        ttk.Button(conn, text="Connect", command=self._connect).grid(row=0, column=6, padx=4)
        ttk.Button(conn, text="List V4L2 ctrls", command=self._list_ctrls).grid(row=0, column=7, padx=4)

        body = ttk.Frame(root)
        body.pack(fill=tk.BOTH, expand=True, pady=8)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Controls
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky=tk.NS)
        ctrl = ttk.LabelFrame(left, text="Preview / WB (software)", padding=8)
        ctrl.pack(fill=tk.X)

        self.ev_v = tk.DoubleVar(value=APPROVED.exposure_ev)
        self.contrast_v = tk.DoubleVar(value=APPROVED.contrast)
        self.sat_v = tk.DoubleVar(value=APPROVED.saturation)
        self.wbr_v = tk.DoubleVar(value=APPROVED.wb_r)
        self.wbg_v = tk.DoubleVar(value=APPROVED.wb_g)
        self.wbb_v = tk.DoubleVar(value=APPROVED.wb_b)
        self.shadows_v = tk.DoubleVar(value=APPROVED.shadows)
        self.highlights_v = tk.DoubleVar(value=APPROVED.highlights)
        self.count_v = tk.IntVar(value=2)

        self.hw_exp_v = tk.IntVar(value=1100)
        self.use_hw_exp = tk.BooleanVar(value=False)

        self._slider(ctrl, "Brightness (EV)", self.ev_v, -2.0, 3.0, 0.05, 0)
        self._slider(ctrl, "Contrast", self.contrast_v, 0.4, 2.0, 0.05, 1)
        self._slider(ctrl, "Saturation", self.sat_v, 0.0, 2.5, 0.05, 2)
        self._slider(ctrl, "Shadows", self.shadows_v, -0.5, 0.8, 0.01, 3)
        self._slider(ctrl, "Highlights", self.highlights_v, -0.5, 0.8, 0.01, 4)
        self._slider(ctrl, "WB Red", self.wbr_v, 0.4, 2.5, 0.01, 5)
        self._slider(ctrl, "WB Green", self.wbg_v, 0.4, 2.5, 0.01, 6)
        self._slider(ctrl, "WB Blue", self.wbb_v, 0.4, 2.5, 0.01, 7)

        hw = ttk.LabelFrame(left, text="Capture / hardware", padding=8)
        hw.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(hw, text="Frames to grab").grid(row=0, column=0, sticky=tk.W)
        ttk.Spinbox(hw, from_=1, to=5, textvariable=self.count_v, width=6).grid(row=0, column=1, sticky=tk.W)
        ttk.Checkbutton(hw, text="Set V4L2 exposure", variable=self.use_hw_exp).grid(
            row=1, column=0, columnspan=2, sticky=tk.W, pady=(6, 0)
        )
        ttk.Label(hw, text="exposure_absolute").grid(row=2, column=0, sticky=tk.W)
        ttk.Spinbox(hw, from_=1, to=65535, textvariable=self.hw_exp_v, width=8).grid(row=2, column=1, sticky=tk.W)

        presets = ttk.LabelFrame(left, text="WB presets", padding=8)
        presets.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(presets, text="Approved", command=self._preset_approved).pack(side=tk.LEFT, padx=2)
        ttk.Button(presets, text="Neutral", command=lambda: self._preset(1, 1, 1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(presets, text="Warm", command=lambda: self._preset(1.2, 1.0, 0.85)).pack(side=tk.LEFT, padx=2)
        ttk.Button(presets, text="Cool", command=lambda: self._preset(0.9, 1.0, 1.25)).pack(side=tk.LEFT, padx=2)


        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=10)
        ttk.Button(btns, text="Start live stream", command=self._toggle_live).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="Take still (full res)", command=self._capture).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="Re-apply preview", command=self._refresh_preview).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="Save JPEG…", command=self._save_jpeg).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="Save as approved look", command=self._save_approved).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="Copy settings report", command=self._copy_report).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="Save settings JSON…", command=self._save_json).pack(fill=tk.X, pady=2)

        # Image + report
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky=tk.NSEW, padx=(10, 0))
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        img_frame = ttk.LabelFrame(right, text="Preview", padding=4)
        img_frame.grid(row=0, column=0, sticky=tk.NSEW)
        img_frame.rowconfigure(0, weight=1)
        img_frame.columnconfigure(0, weight=1)
        self.img_label = ttk.Label(img_frame, anchor=tk.CENTER, background="#222")
        self.img_label.grid(row=0, column=0, sticky=tk.NSEW)

        self.status = tk.StringVar(value="Disconnected.")
        ttk.Label(right, textvariable=self.status, wraplength=700).grid(row=1, column=0, sticky=tk.EW, pady=(6, 0))

        self.report = tk.Text(right, height=8, wrap=tk.WORD)
        self.report.grid(row=2, column=0, sticky=tk.EW, pady=(6, 0))
        self._write_report()

    def _slider(
        self,
        parent: ttk.LabelFrame,
        label: str,
        var: tk.DoubleVar,
        lo: float,
        hi: float,
        res: float,
        row: int,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W)
        val = ttk.Label(parent, text=f"{var.get():.2f}", width=6)
        val.grid(row=row, column=2, sticky=tk.E)

        def on_change(_=None) -> None:
            val.configure(text=f"{var.get():.2f}")
            self._sync_settings()
            self._write_report()
            if self._raw_img is not None:
                self._refresh_preview()

        sc = ttk.Scale(
            parent,
            from_=lo,
            to=hi,
            variable=var,
            orient=tk.HORIZONTAL,
            length=220,
            command=lambda _v: on_change(),
        )
        sc.grid(row=row, column=1, sticky=tk.EW, padx=6)
        parent.columnconfigure(1, weight=1)
        var.trace_add("write", lambda *_: on_change())

    def _preset(self, r: float, g: float, b: float) -> None:
        self.wbr_v.set(r)
        self.wbg_v.set(g)
        self.wbb_v.set(b)
        self._refresh_preview()

    def _preset_approved(self) -> None:
        self.ev_v.set(APPROVED.exposure_ev)
        self.contrast_v.set(APPROVED.contrast)
        self.sat_v.set(APPROVED.saturation)
        self.wbr_v.set(APPROVED.wb_r)
        self.wbg_v.set(APPROVED.wb_g)
        self.wbb_v.set(APPROVED.wb_b)
        self.shadows_v.set(APPROVED.shadows)
        self.highlights_v.set(APPROVED.highlights)
        self._refresh_preview()

    def _sync_settings(self) -> None:
        self.settings.exposure_ev = float(self.ev_v.get())
        self.settings.contrast = float(self.contrast_v.get())
        self.settings.saturation = float(self.sat_v.get())
        self.settings.wb_r = float(self.wbr_v.get())
        self.settings.wb_g = float(self.wbg_v.get())
        self.settings.wb_b = float(self.wbb_v.get())
        self.settings.shadows = float(self.shadows_v.get())
        self.settings.highlights = float(self.highlights_v.get())
        self.settings.capture_count = int(self.count_v.get())
        self.settings.hw_exposure = int(self.hw_exp_v.get()) if self.use_hw_exp.get() else None

    def _settings_report(self) -> str:
        self._sync_settings()
        s = self.settings
        lines = [
            f"timestamp: {datetime.now().isoformat(timespec='seconds')}",
            f"host: {self.host_v.get()}",
            "",
            "software_preview:",
            f"  exposure_ev: {s.exposure_ev:.3f}",
            f"  contrast: {s.contrast:.3f}",
            f"  saturation: {s.saturation:.3f}",
            f"  shadows: {s.shadows:.3f}",
            f"  highlights: {s.highlights:.3f}",
            f"  wb_r: {s.wb_r:.3f}",
            f"  wb_g: {s.wb_g:.3f}",
            f"  wb_b: {s.wb_b:.3f}",
            "",
            "capture:",
            f"  frames: {s.capture_count}",
            f"  hw_exposure_absolute: {s.hw_exposure}",
            "",
            "notes: paste anything useful (lighting, still green?, etc.)",
        ]
        return "\n".join(lines)

    def _write_report(self) -> None:
        text = self._settings_report()
        self.report.delete("1.0", tk.END)
        self.report.insert(tk.END, text)

    def _set_status(self, msg: str) -> None:
        self.status.set(msg)
        self.update_idletasks()

    def _bg(self, work, done=None) -> None:
        if self._busy:
            self._set_status("Busy — wait for current job.")
            return
        self._busy = True

        def runner() -> None:
            err = None
            result = None
            try:
                result = work()
            except Exception as e:
                err = e
            def finish() -> None:
                self._busy = False
                if err:
                    self._set_status(f"Error: {err}")
                    messagebox.showerror("Camera tuner", str(err))
                elif done:
                    done(result)
            self.after(0, finish)

        threading.Thread(target=runner, daemon=True).start()

    def _connect(self) -> None:
        def work():
            self.cam = TabletCam(self.host_v.get().strip(), self.user_v.get().strip(), self.pass_v.get())
            self.cam.connect()
            return self.cam.ensure_camera()

        def done(out: str) -> None:
            self._set_status("Connected. Camera node ready.")
            # Keep a short snippet visible
            snippet = "\n".join(out.strip().splitlines()[:12])
            if snippet:
                self._set_status(f"Connected.\n{snippet}")

        self._set_status("Connecting…")
        self._bg(work, done)

    def _list_ctrls(self) -> None:
        def work():
            if not self.cam._client:
                self.cam.connect()
            return self.cam.list_controls()

        def done(out: str) -> None:
            top = tk.Toplevel(self)
            top.title("V4L2 controls")
            top.geometry("640x480")
            t = tk.Text(top, wrap=tk.NONE)
            t.pack(fill=tk.BOTH, expand=True)
            t.insert(tk.END, out or "(no controls reported)")
            t.configure(state=tk.DISABLED)

        self._set_status("Listing controls…")
        self._bg(work, done)

    def _capture(self) -> None:
        self._sync_settings()

        def work():
            if not self.cam._client:
                self.cam.connect()
                self.cam.ensure_camera()
            return self.cam.capture_jpeg(self.settings)

        def done(data: bytes) -> None:
            img = Image.open(io.BytesIO(data))
            self._raw_img = img.convert("RGB")
            # Also stash untouched capture
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            raw_path = LOGS / f"tuner_raw_{stamp}.jpg"
            self._raw_img.save(raw_path, quality=92)
            self._refresh_preview()
            self._write_report()
            self._set_status(f"Captured {self._raw_img.size[0]}x{self._raw_img.size[1]} — saved {raw_path.name}")

        self._set_status("Capturing (10–25s)…")
        self._bg(work, done)

    def _refresh_preview(self) -> None:
        if self._raw_img is None:
            return
        self._sync_settings()
        tuned = apply_software(self._raw_img, self.settings)
        # Fit into label area
        self.update_idletasks()
        max_w = max(400, self.img_label.winfo_width() - 8)
        max_h = max(300, self.img_label.winfo_height() - 8)
        preview = ImageOps.contain(tuned, (max_w, max_h))
        self._photo = ImageTk.PhotoImage(preview)
        self.img_label.configure(image=self._photo)
        self._write_report()

    def _toggle_live(self) -> None:
        if self._live:
            self._live = False
            self._set_status("Live stream stopping…")
            return
        self._live = True
        self._set_status("Live stream starting (plain frames + local grade)…")
        self._live_thread = threading.Thread(target=self._live_loop, daemon=True)
        self._live_thread.start()

    def _live_loop(self) -> None:
        host = self.host_v.get().strip()
        url = f"http://{host}:{STREAM_PORT}/stream.mjpg?plain=1"
        buf = b""
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                while self._live:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        start = buf.find(b"\xff\xd8")
                        if start < 0:
                            buf = buf[-1:] if buf else b""
                            break
                        if start:
                            buf = buf[start:]
                        end = buf.find(b"\xff\xd9", 2)
                        if end < 0:
                            break
                        jpeg = buf[: end + 2]
                        buf = buf[end + 2 :]
                        try:
                            img = Image.open(io.BytesIO(jpeg)).convert("RGB")
                        except Exception:
                            continue

                        def show(i=img) -> None:
                            if not self._live:
                                return
                            self._raw_img = i
                            self._refresh_preview()
                            self._set_status(f"Live {i.size[0]}x{i.size[1]} — move sliders to grade")

                        self.after(0, show)
        except Exception as exc:
            def fail() -> None:
                self._live = False
                self._set_status(f"Live stream error: {exc}")

            self.after(0, fail)
        finally:
            self._live = False

    def _save_approved(self) -> None:
        self._sync_settings()
        s = self.settings
        look = PreviewLook(
            exposure_ev=s.exposure_ev,
            contrast=s.contrast,
            saturation=s.saturation,
            wb_r=s.wb_r,
            wb_g=s.wb_g,
            wb_b=s.wb_b,
            shadows=s.shadows,
            highlights=s.highlights,
        )
        payload = {
            "version": 1,
            "approved_at": datetime.now().isoformat(timespec="seconds"),
            "host": self.host_v.get().strip(),
            "software_preview": look.to_software_dict(),
            "capture": {
                "frames": s.capture_count,
                "width": 1584,
                "height": 1184,
                "stride_width": 1600,
                "pixelformat": "NV12",
            },
            "notes": "Dialled in via tools/cam_tuner_gui.py",
        }
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if self._raw_img is not None:
            stamped = LOGS / f"cam_approved_look_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            apply_software(self._raw_img, s).save(stamped, quality=95)
            apply_software(self._raw_img, s).save(LOGS / "cam_approved_look.jpg", quality=95)
        self._set_status(f"Saved approved look → {CONFIG}")
        messagebox.showinfo(
            "Camera tuner",
            f"Wrote {CONFIG}\nRedeploy the camera stream service to push this look to the tablet/HA.",
        )

    def _save_jpeg(self) -> None:
        if self._raw_img is None:
            messagebox.showinfo("Camera tuner", "Take a photo first.")
            return
        self._sync_settings()
        tuned = apply_software(self._raw_img, self.settings)
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg")],
            initialdir=str(LOGS),
            initialfile=f"tuner_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
        )
        if not path:
            return
        tuned.save(path, quality=95)
        # sidecar settings
        Path(path + ".settings.txt").write_text(self._settings_report(), encoding="utf-8")
        self._set_status(f"Saved {path}")

    def _copy_report(self) -> None:
        text = self._settings_report()
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("Settings report copied to clipboard — paste it back here in chat.")

    def _save_json(self) -> None:
        self._sync_settings()
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=str(LOGS),
            initialfile=f"tuner_settings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        if not path:
            return
        Path(path).write_text(json.dumps(asdict(self.settings), indent=2), encoding="utf-8")
        self._set_status(f"Wrote {path}")

    def _on_close(self) -> None:
        self._live = False
        try:
            self.cam.close()
        finally:
            self.destroy()


def main() -> None:
    app = CamTunerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
