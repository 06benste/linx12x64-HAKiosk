#!/usr/bin/env python3
"""Apply X11 kiosk migration — upload wrapper then sudo bash /tmp/file."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
USER = "kioskuser"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
sed -i 's/\r$//' /tmp/05-x11-kiosk.sh /tmp/06-no-sleep.sh
chmod +x /tmp/05-x11-kiosk.sh /tmp/06-no-sleep.sh
bash /tmp/05-x11-kiosk.sh
bash /tmp/06-no-sleep.sh || true

python3 - <<'PY'
from pathlib import Path
import re
p = Path('/etc/default/grub')
params = 'intel_idle.max_cstate=0 i915.enable_psr=0 i915.enable_fbc=0 i915.enable_dc=0 idle=nomwait'
text = p.read_text()
text2, n = re.subn(
    r'^GRUB_CMDLINE_LINUX_DEFAULT=.*$',
    f'GRUB_CMDLINE_LINUX_DEFAULT="{params}"',
    text,
    flags=re.M,
)
if n == 0:
    text2 = text.rstrip() + f'\nGRUB_CMDLINE_LINUX_DEFAULT="{params}"\n'
p.write_text(text2)
print('grub ok', params)
PY
update-grub

cat > /home/kioskuser/.xinitrc <<'EOF'
#!/bin/sh
xset s off
/opt/ha-kiosk/scripts/keep-awake-x11.sh &
exec /opt/ha-kiosk/scripts/kiosk-x11.sh
EOF
chmod 755 /home/kioskuser/.xinitrc
chown kioskuser:kioskuser /home/kioskuser/.xinitrc

cat > /opt/ha-kiosk/scripts/kiosk-x11.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
INSTALL_ROOT=/opt/ha-kiosk
URL="$(cat "$INSTALL_ROOT/url" 2>/dev/null || true)"
[[ -n "$URL" ]] || URL='http://192.168.8.110:8123/dashboard-kiosk?kiosk'
PROFILE_DIR=$INSTALL_ROOT/chromium-profile
EXT_DIR=$INSTALL_ROOT/chromium-extension
mkdir -p "$PROFILE_DIR"
command -v unclutter >/dev/null && unclutter -idle 0.5 -root &
CHROME=/usr/lib/chromium/chromium
[[ -x "$CHROME" ]] || CHROME="$(command -v chromium)"
EXTRA=()
if [[ -f "$EXT_DIR/manifest.json" ]]; then
  EXTRA+=(--disable-extensions-except="$EXT_DIR" --load-extension="$EXT_DIR")
else
  EXTRA+=(--disable-extensions)
fi
exec "$CHROME" \
  --user-data-dir="$PROFILE_DIR" \
  --ozone-platform=x11 \
  --kiosk --start-fullscreen \
  --no-first-run --noerrdialogs --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-translate --disable-sync \
  --disable-features=TranslateUI,AudioServiceOutOfProcess,UseChromeOSDirectVideoDecoder \
  --check-for-update-interval=31536000 \
  --password-store=basic \
  --autoplay-policy=no-user-gesture-required \
  --disk-cache-size=33554432 \
  --disable-pinch \
  --disable-gpu --disable-gpu-compositing --disable-gpu-rasterization \
  --disable-accelerated-2d-canvas --disable-accelerated-video-decode \
  --disable-software-rasterizer --use-gl=swiftshader \
  --disable-dev-shm-usage \
  "${EXTRA[@]}" \
  "$URL"
EOF
chmod 755 /opt/ha-kiosk/scripts/kiosk-x11.sh
chown -R kioskuser:kioskuser /opt/ha-kiosk

echo '--- bash_profile ---'
cat /home/kioskuser/.bash_profile
echo APPLY_OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20, allow_agent=False, look_for_keys=False)

    sftp = client.open_sftp()
    for name in ("05-x11-kiosk.sh", "06-no-sleep.sh"):
        sftp.put(str(ROOT / "scripts" / name), f"/tmp/{name}")
        print(f"uploaded {name}", flush=True)
    with sftp.file("/tmp/apply-x11.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/apply-x11.sh", 0o755)
    print("uploaded apply-x11.sh", flush=True)
    sftp.close()

    cmd = f"echo {PASS} | sudo -S -p '' bash /tmp/apply-x11.sh"
    stdin, stdout, stderr = client.exec_command(cmd, timeout=420)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out[-12000:] if len(out) > 12000 else out)
    if err.strip():
        lines = [l for l in err.splitlines() if "password" not in l.lower()]
        print("STDERR:\n" + "\n".join(lines)[-5000:])
    print("exit:", code, flush=True)
    if code != 0 or "APPLY_OK" not in out:
        client.close()
        sys.exit(1)

    print("Rebooting...", flush=True)
    try:
        client.exec_command(f"echo {PASS} | sudo -S -p '' reboot", timeout=10)
        time.sleep(3)
    except Exception:
        pass
    client.close()

    print("Waiting for SSH after reboot...", flush=True)
    time.sleep(35)
    deadline = time.time() + 360
    while time.time() < deadline:
        try:
            c2 = paramiko.SSHClient()
            c2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c2.connect(HOST, username=USER, password=PASS, timeout=8, allow_agent=False, look_for_keys=False)
            stdin, stdout, stderr = c2.exec_command(
                "uptime; cat /proc/cmdline; echo ---; "
                "ps aux | grep -E 'Xorg|chromium|startx|cage' | grep -v grep || true; echo ---; "
                "cat ~/.bash_profile; echo ---; "
                "systemctl is-active ha-kiosk-inhibit-sleep.service ha-kiosk-noblank.service 2>/dev/null || true; "
                "ls -l /dev/dri 2>/dev/null || echo no-dri",
                timeout=60,
            )
            print(stdout.read().decode("utf-8", errors="replace"))
            c2.close()
            print("DONE", flush=True)
            return
        except Exception as exc:
            print(f"wait: {exc}", flush=True)
            time.sleep(5)
    print("SSH did not return after reboot", flush=True)
    sys.exit(2)


if __name__ == "__main__":
    main()
