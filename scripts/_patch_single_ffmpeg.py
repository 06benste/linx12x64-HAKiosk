#!/usr/bin/env python3
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "scripts" / "camera-stream-server.py"
text = p.read_text(encoding="utf-8")
start = text.index("        try:\n            if PLAIN_FIFO.exists():")
end = text.index("    def _pump_frames(self, v4l: subprocess.Popen[bytes], ff: subprocess.Popen[bytes]) -> None:")
new = r'''        vf = build_stream_vf(self._look)

        try:
            v4l = subprocess.Popen(
                [
                    "v4l2-ctl",
                    "-d",
                    "/dev/video0",
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
                    "-vf",
                    vf,
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
                stderr=subprocess.PIPE,
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
        print(
            f"camera stream started v4l={v4l.pid} ff={ff.pid} "
            f"{WIDTH}x{HEIGHT}@{FPS} frame={FRAME_SIZE}",
            flush=True,
        )

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            v4l, ff = self._v4l, self._ff
            self._v4l = None
            self._ff = None
            self._plain_fh = None
        for proc in (ff, v4l):
            if not proc:
                continue
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        subprocess.run(["pkill", "-9", "-f", "v4l2-ctl --stream"], check=False)
        subprocess.run(
            ["pkill", "-9", "-f", "ffmpeg.*rawvideo.*1600x1184"],
            check=False,
        )
        print("camera stream stopped", flush=True)

'''
p.write_text(text[:start] + new + text[end:], encoding="utf-8")
print("OK patched")
