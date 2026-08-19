#!/usr/bin/env python3
import time
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"


def ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    return c


def uptime_seconds(c) -> float:
    _, o, _ = c.exec_command("cut -d. -f1 /proc/uptime", timeout=10)
    return float(o.read().decode().strip() or "0")


def main() -> None:
    c = ssh()
    before = uptime_seconds(c)
    print(f"uptime before: {before}s", flush=True)
    # fire-and-forget reboot
    transport = c.get_transport()
    chan = transport.open_session()
    chan.exec_command(f"echo {PASS} | sudo -S -p '' /sbin/shutdown -r now")
    time.sleep(1)
    try:
        c.close()
    except Exception:
        pass
    print("reboot requested; waiting...", flush=True)
    time.sleep(35)
    for i in range(60):
        try:
            c = ssh()
            after = uptime_seconds(c)
            _, o, _ = c.exec_command(
                "test -e /dev/video0 && echo VID_OK || echo VID_MISS; "
                "v4l2-ctl -d /dev/video0 --get-fmt-video 2>&1 | head -8",
                timeout=15,
            )
            print(f"back uptime={after}s\n{o.read().decode()}", flush=True)
            c.close()
            if after < before:
                print("reboot confirmed", flush=True)
            else:
                print("WARNING: uptime did not reset", flush=True)
            return
        except Exception as exc:
            print(f"wait {i}: {exc}", flush=True)
            time.sleep(5)
    raise SystemExit("did not come back")


if __name__ == "__main__":
    main()
