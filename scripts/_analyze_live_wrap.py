#!/usr/bin/env python3
"""Pull live graded snapshot and find horizontal wrap offset."""
import io
import json
import time
from pathlib import Path

import numpy as np
import paramiko
from PIL import Image

HOST, PASS = "192.168.8.201", "kiosk"
OUT = Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
OUT.mkdir(exist_ok=True)


def sudo_script(c, body, timeout=60):
    sftp = c.open_sftp()
    with sftp.file("/tmp/_agent_job.sh", "w") as f:
        f.write("#!/bin/bash\nset -e\n" + body + "\n")
    sftp.chmod("/tmp/_agent_job.sh", 0o755)
    sftp.close()
    chan = c.get_transport().open_session()
    chan.settimeout(timeout)
    chan.get_pty()
    chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_agent_job.sh")
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if chan.recv_ready():
            buf += chan.recv(65536)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(65536)
            break
        time.sleep(0.05)
    return buf.decode("utf-8", "replace")


def find_wrap(im: np.ndarray) -> dict:
    h, w, _ = im.shape
    # Try strip widths from 4% to 20%
    results = []
    for frac in np.linspace(0.04, 0.22, 19):
        sw = max(8, int(round(w * float(frac))))
        left = im[:, :sw]
        best_err, best_x = 1e18, None
        # Search where left strip appears in the rest of the image
        for x in range(sw, w - sw + 1, 1):
            ref = im[:, x : x + sw]
            err = float(np.mean((left - ref) ** 2))
            if err < best_err:
                best_err, best_x = err, x
        # Compare to far-right strip specifically
        right = im[:, -sw:]
        right_err = float(np.mean((left - right) ** 2))
        # Global image variance for context
        var = float(np.var(im))
        results.append(
            {
                "sw": sw,
                "frac": float(frac),
                "best_x": best_x,
                "best_err": best_err,
                "right_err": right_err,
                "norm_right": right_err / max(var, 1e-6),
                "norm_best": best_err / max(var, 1e-6),
            }
        )
    # Prefer matches near the right edge with low error
    scored = sorted(results, key=lambda r: (r["norm_right"], -r["sw"]))
    return {"w": w, "h": h, "var": float(np.var(im)), "candidates": scored[:8], "all_right": scored}


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    print(
        sudo_script(
            c,
            "systemctl is-active ha-kiosk-camera-stream.service; "
            "curl -fsS --max-time 3 http://127.0.0.1:17824/health; echo; "
            # wake + snap
            "python3 - <<'PY'\n"
            "import urllib.request,threading,time\n"
            "def suck():\n"
            "  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg',timeout=8).read(2048)\n"
            "  except Exception: pass\n"
            "threading.Thread(target=suck,daemon=True).start(); time.sleep(2)\n"
            "open('/tmp/live_wrap.jpg','wb').write(urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg',timeout=20).read())\n"
            "print('snap', __import__('os').path.getsize('/tmp/live_wrap.jpg'))\n"
            "PY",
            timeout=50,
        )
    )
    sftp = c.open_sftp()
    data = sftp.file("/tmp/live_wrap.jpg", "rb").read()
    sftp.close()
    c.close()
    (OUT / "live_wrap.jpg").write_bytes(data)
    im = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float32)
    info = find_wrap(im)
    print("size", info["w"], info["h"], "var", round(info["var"], 1))
    for r in info["candidates"]:
        print(
            f"sw={r['sw']:3d} ({r['frac']:.0%}) right_err={r['right_err']:.0f} "
            f"normR={r['norm_right']:.3f} best_x={r['best_x']} normBest={r['norm_best']:.3f}"
        )

    # Build corrected image by rolling left strip to right for best right-match sw
    best = min(info["all_right"], key=lambda r: r["norm_right"])
    sw = best["sw"]
    print("CHOSEN_WRAP_PX", sw, "normR", round(best["norm_right"], 3))
    rolled = np.concatenate([im[:, sw:], im[:, :sw]], axis=1)
    Image.fromarray(rolled.astype(np.uint8)).save(OUT / "live_wrap_fixed.jpg")
    # Also save with common guesses 64,80,96 at sensor->800 scale (~40,50,60?); at 800: try 72-96
    for sw2 in (64, 72, 80, 88, 96, 112, 128):
        rolled2 = np.concatenate([im[:, sw2:], im[:, :sw2]], axis=1)
        Image.fromarray(rolled2.astype(np.uint8)).save(OUT / f"live_roll_{sw2}.jpg")
        # re-score seam at 0 after roll (continuity)
        seam = float(np.mean(np.abs(rolled2[:, 0] - rolled2[:, -1])))  # not useful
        mid = rolled2.shape[1] // 2
        # continuity at former seam location: now at w-sw2 junction... actually after roll seam should be gone at x=0
        c0 = float(np.mean(np.abs(rolled2[:, 1] - rolled2[:, 0])))
        print(f"roll_{sw2}: edge_cont={c0:.2f}")


if __name__ == "__main__":
    main()
