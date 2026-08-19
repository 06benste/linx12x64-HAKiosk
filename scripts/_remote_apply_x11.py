#!/usr/bin/env python3
"""Upload and run X11 kiosk migration on hakiosk. Retries until SSH is up."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
USER = "kioskuser"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = [
    ROOT / "scripts" / "05-x11-kiosk.sh",
    ROOT / "scripts" / "06-no-sleep.sh",
]


REMOTE_WRAPPER = r"""
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
cd /tmp
# Normalize CRLF if any
sed -i 's/\r$//' 05-x11-kiosk.sh 06-no-sleep.sh
chmod +x 05-x11-kiosk.sh 06-no-sleep.sh

# Harden GPU params beyond script defaults (Cherry Trail hangs)
python3 - <<'PY'
from pathlib import Path
import re
p = Path('/etc/default/grub')
text = p.read_text()
# Replace GRUB_CMDLINE_LINUX_DEFAULT with cleaned params
params = (
    'intel_idle.max_cstate=0 '
    'i915.enable_psr=0 i915.enable_fbc=0 i915.enable_dc=0 '
    'idle=nomwait'
)
text2, n = re.subn(
    r'^GRUB_CMDLINE_LINUX_DEFAULT=.*$',
    f'GRUB_CMDLINE_LINUX_DEFAULT="{params}"',
    text,
    flags=re.M,
)
if n == 0:
    text2 = text.rstrip() + f'\nGRUB_CMDLINE_LINUX_DEFAULT="{params}"\n'
p.write_text(text2)
print('grub pre-set')
PY

bash ./05-x11-kiosk.sh
bash ./06-no-sleep.sh || true

# Prefer chromium binary (avoids Debian wrapper GPU flags) and force X11 ozone
cat > /opt/ha-kiosk/scripts/kiosk-x11.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
INSTALL_ROOT="/opt/ha-kiosk"
URL="$(cat "$INSTALL_ROOT/url" 2>/dev/null || true)"
[[ -n "$URL" ]] || URL="http://192.168.8.110:8123/dashboard-kiosk?kiosk"
PROFILE_DIR="$INSTALL_ROOT/chromium-profile"
EXT_DIR="$INSTALL_ROOT/chromium-extension"
mkdir -p "$PROFILE_DIR"
command -v unclutter >/dev/null && unclutter -idle 0.5 -root &
CHROME="/usr/lib/chromium/chromium"
[[ -x "$CHROME" ]] || CHROME="$(command -v chromium || command -v chromium-browser)"
EXTRA=()
if [[ -f "$EXT_DIR/manifest.json" && -f "$EXT_DIR/config.js" ]]; then
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
chown kioskuser:kioskuser /opt/ha-kiosk/scripts/kiosk-x11.sh

# Keep screen awake inside X
cat > /home/kioskuser/.xinitrc <<'EOF'
#!/bin/sh
xset s off
/opt/ha-kiosk/scripts/keep-awake-x11.sh &
exec /opt/ha-kiosk/scripts/kiosk-x11.sh
EOF
chmod 755 /home/kioskuser/.xinitrc
chown kioskuser:kioskuser /home/kioskuser/.xinitrc

update-grub
echo APPLY_OK
"""


def wait_ssh(timeout: int = 1200) -> paramiko.SSHClient:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                HOST,
                username=USER,
                password=PASS,
                timeout=8,
                banner_timeout=20,
                auth_timeout=20,
                allow_agent=False,
                look_for_keys=False,
            )
            print(f"SSH connected on attempt {attempt}")
            return client
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt == 1 or attempt % 6 == 0:
                print(f"SSH wait #{attempt}: {exc}")
            time.sleep(5)
    raise RuntimeError(f"SSH never came up: {last_err}")


def sudo_bash(client: paramiko.SSHClient, script: str, timeout: int = 600) -> tuple[str, str, int]:
    cmd = "echo kiosk | sudo -S -p '' bash -s"
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    stdin.write(script)
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return out, err, code


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("Waiting for SSH...")
    client = wait_ssh(1200)
    print("SSH up — gathering crash evidence first")
    _, out, _ = None, "", 0
    stdin, stdout, stderr = client.exec_command(
        "uptime; last -x | head -n 20; echo ---; cat /proc/cmdline; echo ---; "
        "ps aux | grep -E 'cage|chromium|Xorg|startx' | grep -v grep; "
        "echo ---; cat ~/.bash_profile 2>/dev/null; echo ---; "
        "free -h; echo ---; "
        "echo kiosk | sudo -S -p '' journalctl -b -1 -k --no-pager 2>/dev/null | tail -n 40",
        timeout=90,
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip() and "password" not in err.lower():
        print("STDERR:", err[:1500])

    print("Uploading scripts...")
    sftp = client.open_sftp()
    for path in SCRIPTS:
        remote = f"/tmp/{path.name}"
        sftp.put(str(path), remote)
        print(f"  -> {remote}")
    sftp.close()

    print("Applying X11 migration + no-sleep + GPU harden...")
    out, err, code = sudo_bash(client, REMOTE_WRAPPER, timeout=600)
    print(out[-6000:] if len(out) > 6000 else out)
    if err.strip():
        lines = [l for l in err.splitlines() if "password" not in l.lower()]
        if lines:
            print("STDERR:", "\n".join(lines)[-3000:])
    print("exit:", code)
    if code != 0 or "APPLY_OK" not in out:
        client.close()
        sys.exit(1)

    print("Rebooting...")
    try:
        sudo_bash(client, "reboot\n", timeout=15)
    except Exception:
        pass
    client.close()

    print("Waiting for SSH after reboot...")
    time.sleep(25)
    client = wait_ssh(900)
    stdin, stdout, stderr = client.exec_command(
        "uptime; cat /proc/cmdline; echo ---; "
        "ps aux | grep -E 'Xorg|chromium|startx|cage' | grep -v grep; "
        "echo ---; cat ~/.bash_profile; echo ---; "
        "systemctl is-active ha-kiosk-inhibit-sleep.service ha-kiosk-noblank.service 2>/dev/null; "
        "ls -l /dev/dri 2>/dev/null || echo no-dri",
        timeout=60,
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    client.close()
    print("DONE")


if __name__ == "__main__":
    main()
