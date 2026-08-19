#!/usr/bin/env python3
"""Reboot tablet with AtomISP firmware + correct module load order, then capture."""
from __future__ import annotations

import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"


def ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST,
        username="kioskuser",
        password=PASS,
        timeout=25,
        allow_agent=False,
        look_for_keys=False,
    )
    return c


def run(c, cmd, timeout=120):
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash -lc {paramiko.py3compat.u_byte(repr(cmd) if False else '')}",
        timeout=timeout,
        get_pty=True,
    )
    # simpler:
    raise NotImplementedError


SETUP = r'''
set -euxo pipefail
mkdir -p /lib/firmware/intel/ipu /opt/ha-kiosk/scripts /etc/modules-load.d
ln -sfn /lib/firmware/shisp_2401a0_v21.bin /lib/firmware/intel/ipu/shisp_2401a0_v21.bin
ls -la /lib/firmware/intel/ipu/shisp_2401a0_v21.bin

# Keep dummy PM blacklisted
cat > /etc/modprobe.d/blacklist-atomisp.conf <<'EOF'
blacklist intel_atomisp2_pm
EOF

# Load order: platform -> atomisp (powers ISP) -> sensors
cat > /opt/ha-kiosk/scripts/load-atomisp.sh <<'EOF'
#!/bin/bash
set -e
modprobe atomisp_gmin_platform || true
# Give PCI device a moment after gmin
sleep 1
modprobe atomisp || true
sleep 2
modprobe atomisp-gc2235 || true
sleep 2
# If sensors loaded before ISP and failed, try once more after ISP is up
if ! dmesg | tail -n 200 | grep -q 'detect gc2235/gc2355 success'; then
  modprobe -r atomisp-gc2235 2>/dev/null || true
  sleep 1
  modprobe atomisp-gc2235 || true
  sleep 2
fi
ls -la /dev/video* /dev/media* 2>&1 || true
dmesg | grep -iE 'atomisp|gc2235|GCTI|shisp|no camera|detect gc' | tail -n 40 || true
EOF
chmod +x /opt/ha-kiosk/scripts/load-atomisp.sh

cat > /etc/systemd/system/ha-kiosk-atomisp.service <<'EOF'
[Unit]
Description=Load AtomISP camera stack for Linx kiosk
After=multi-user.target
Before=ha-kiosk-mqtt.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/ha-kiosk/scripts/load-atomisp.sh

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable ha-kiosk-atomisp.service

echo SETUP_OK
sync
'''

POST = r'''
set -euxo pipefail
/opt/ha-kiosk/scripts/load-atomisp.sh || true
sleep 2
echo '=== status ==='
lspci -nnk -s 00:03.0
ls -la /dev/video* /dev/media* /dev/v4l-subdev* 2>&1 || true
v4l2-ctl --list-devices 2>&1 || true
media-ctl -d /dev/media0 -p 2>&1 | head -n 120 || true
echo '=== dmesg ==='
dmesg | grep -iE 'atomisp|gc2235|GCTI|shisp|firmware|no camera|detect gc|ISP HPLL' | tail -n 80
echo '=== capture ==='
rm -f /tmp/camtest.jpg
# Try common AtomISP formats
for fmt in NV12 YUYV MJPEG; do
  echo "try $fmt"
  timeout 25 ffmpeg -y -f v4l2 -input_format $(echo $fmt | tr A-Z a-z) -video_size 1280x720 -i /dev/video0 -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 15 && break || true
  timeout 25 ffmpeg -y -f v4l2 -video_size 640x480 -i /dev/video0 -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 15 && break || true
done
ls -la /tmp/camtest.jpg 2>&1 || true
file /tmp/camtest.jpg 2>&1 || true
# Also try v4l2-ctl stream
v4l2-ctl -d /dev/video0 --list-formats-ext 2>&1 | head -n 80 || true
echo POST_OK
'''


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = ssh()
    sftp = c.open_sftp()
    with sftp.file("/tmp/cam-setup.sh", "w") as f:
        f.write(SETUP.replace("\r\n", "\n"))
    sftp.chmod("/tmp/cam-setup.sh", 0o755)
    sftp.close()

    print("=== setup before reboot ===", flush=True)
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/cam-setup.sh",
        timeout=120,
        get_pty=True,
    )
    print(stdout.read().decode("utf-8", errors="replace")[-4000:], flush=True)

    print("=== rebooting tablet ===", flush=True)
    try:
        c.exec_command(f"echo {PASS} | sudo -S -p '' reboot", timeout=10)
    except Exception:
        pass
    c.close()

    print("waiting for reboot...", flush=True)
    time.sleep(25)
    for i in range(60):
        try:
            c = ssh()
            _, o, _ = c.exec_command(
                "uptime; test -x /opt/ha-kiosk/scripts/load-atomisp.sh && echo READY",
                timeout=15,
            )
            out = o.read().decode()
            print(f"ping {i}: {out.strip()}", flush=True)
            if "READY" in out:
                break
            c.close()
        except Exception as e:
            print(f"ping {i}: down ({e})", flush=True)
            time.sleep(5)
    else:
        raise SystemExit("tablet did not come back")

    # Wait a bit more for services; rewrite post script (tmpfs wiped on reboot)
    time.sleep(10)
    sftp = c.open_sftp()
    with sftp.file("/tmp/cam-post.sh", "w") as f:
        f.write(POST.replace("\r\n", "\n"))
    sftp.chmod("/tmp/cam-post.sh", 0o755)
    sftp.close()
    print("=== post reboot camera check ===", flush=True)
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/cam-post.sh",
        timeout=300,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    code = stdout.channel.recv_exit_status()
    print("exit", code, flush=True)

    # Pull image if present
    try:
        sftp = c.open_sftp()
        sftp.get("/tmp/camtest.jpg", "logs/camtest.jpg")
        print("saved logs/camtest.jpg", flush=True)
        sftp.close()
    except Exception as e:
        print("no image:", e, flush=True)
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
