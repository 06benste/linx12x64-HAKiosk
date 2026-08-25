#!/usr/bin/env python3
"""Push updated runtime files to an already-installed tablet and restart
whatever services they belong to.

This replaces the growing pile of one-off `_remote_deploy_*.py` scripts —
one general, reusable tool instead of writing a new throwaway script for
every change. It only handles the fast, no-reboot-needed runtime files
(Python services, the setup wizard's HTML, the chromium extension); it
does not touch anything install.sh's slower/riskier steps own (Wi-Fi
firmware, the GPU fix, the camera's DKMS kernel build) — re-run those
scripts directly on the tablet (over SSH) if something in that territory
changed.

Requires `pip install paramiko` on the machine running this script. Needs
nothing extra on the tablet beyond what install.sh already sets up.

Usage:
    python tools/deploy_to_tablet.py <host> --all
    python tools/deploy_to_tablet.py <host> --only power-api mqtt-bridge
    python tools/deploy_to_tablet.py <host> --list
"""
from __future__ import annotations

import argparse
import pathlib
import shlex
import sys

try:
    import paramiko
except ImportError:
    raise SystemExit("pip install paramiko") from None

ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALL_ROOT = "/opt/ha-kiosk"

# name -> (repo-relative source, device dest, file mode, [services to restart])
# A source ending in "/" is a whole-directory copy (chown -R at the end
# covers everything under it); services are restarted after ALL selected
# targets are uploaded, deduplicated, in the order first requested.
TARGETS: dict[str, tuple[str, str, str, list[str]]] = {
    "power-api": (
        "scripts/power-api.py", f"{INSTALL_ROOT}/scripts/power-api.py", "755",
        ["ha-kiosk-power.service"],
    ),
    "mqtt-bridge": (
        "scripts/ha-kiosk-mqtt.py", f"{INSTALL_ROOT}/scripts/ha-kiosk-mqtt.py", "755",
        ["ha-kiosk-mqtt.service"],
    ),
    "setup-wizard": (
        "scripts/setup-wizard.py", f"{INSTALL_ROOT}/scripts/setup-wizard.py", "755",
        ["ha-kiosk-setup.service"],
    ),
    "setup-html": (
        "scripts/static/setup.html", f"{INSTALL_ROOT}/scripts/static/setup.html", "644",
        ["ha-kiosk-setup.service"],
    ),
    "setup-osk": (
        "scripts/static/osk.js", f"{INSTALL_ROOT}/scripts/static/osk.js", "644",
        ["ha-kiosk-setup.service"],
    ),
    "self-update": (
        "scripts/self-update.py", f"{INSTALL_ROOT}/scripts/self-update.py", "755",
        [],
    ),
    "camera-server": (
        "scripts/camera-stream-server.py", f"{INSTALL_ROOT}/scripts/camera-stream-server.py", "755",
        ["ha-kiosk-camera-stream.service"],
    ),
    "cam-tuner-html": (
        "scripts/static/cam-tuner.html", f"{INSTALL_ROOT}/scripts/static/cam-tuner.html", "644",
        ["ha-kiosk-camera-stream.service"],
    ),
    "battery-guard": (
        "scripts/battery-guard.py", f"{INSTALL_ROOT}/scripts/battery-guard.py", "755",
        ["ha-kiosk-battery-guard.service"],
    ),
    "guardian": (
        "scripts/kiosk-guardian.py", f"{INSTALL_ROOT}/scripts/kiosk-guardian.py", "755",
        ["ha-kiosk-guardian.service"],
    ),
    "extension": (
        "chromium-extension/", f"{INSTALL_ROOT}/chromium-extension/", "644",
        ["getty@tty1.service"],
    ),
}


def build_remote_script(uploads: list[tuple[str, str, str]], services: list[str]) -> str:
    """uploads here are single-file targets only — whole-directory targets
    (extension/) are uploaded file-by-file over SFTP directly in main(),
    each with its own mkdir -p, so there's nothing left for this script to
    place for those; it just needs to chown + restart at the end."""
    lines = ["#!/bin/bash", "set -euxo pipefail"]
    for _repo_src, dest, mode in uploads:
        remote_dir = str(pathlib.PurePosixPath(dest).parent)
        fname = pathlib.PurePosixPath(dest).name
        lines.append(f"install -d -m 755 {shlex.quote(remote_dir)}")
        lines.append(f"install -m {mode} {shlex.quote('/tmp/ha-deploy/' + fname)} {shlex.quote(dest)}")
    lines.append(f"chown -R kioskuser:kioskuser {shlex.quote(INSTALL_ROOT)}")
    lines.append("systemctl daemon-reload")
    for svc in services:
        lines.append(f"systemctl restart {shlex.quote(svc)} || true")
    lines.append("echo DEPLOY_OK")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", nargs="?", help="tablet IP or hostname")
    ap.add_argument("--user", default="kioskuser")
    ap.add_argument("--password", default="kiosk", help="sudo/SSH password (default matches this project's standard tablet password)")
    ap.add_argument("--all", action="store_true", help="deploy every known target")
    ap.add_argument("--only", nargs="+", metavar="TARGET", help="deploy just these targets (see --list)")
    ap.add_argument("--list", action="store_true", help="list known targets and exit")
    args = ap.parse_args()

    if args.list or not args.host:
        print("Known targets:")
        for name, (src, dest, _mode, services) in TARGETS.items():
            print(f"  {name:16s} {src} -> {dest}  (restarts: {', '.join(services)})")
        return

    if args.all:
        names = list(TARGETS.keys())
    elif args.only:
        unknown = [n for n in args.only if n not in TARGETS]
        if unknown:
            raise SystemExit(f"unknown target(s): {', '.join(unknown)} — see --list")
        names = args.only
    else:
        raise SystemExit("specify --all or --only TARGET [TARGET ...] (see --list)")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=args.password, timeout=20, allow_agent=False, look_for_keys=False)

    sftp = client.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-deploy")
    except OSError:
        pass

    uploads: list[tuple[str, str, str]] = []
    services: list[str] = []
    for name in names:
        src, dest, mode, svcs = TARGETS[name]
        local = ROOT / src
        if src.endswith("/"):
            if not local.is_dir():
                print(f"skip {name}: {local} not found", file=sys.stderr)
                continue
            for f in local.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(local)
                    remote_dest = dest + str(rel).replace("\\", "/")
                    remote_dir = str(pathlib.PurePosixPath(remote_dest).parent)
                    _mkdir_p(sftp, remote_dir)
                    data = f.read_bytes().replace(b"\r\n", b"\n") if f.suffix in (".js", ".json", ".html", ".css") else f.read_bytes()
                    with sftp.file(remote_dest, "wb") as fh:
                        fh.write(data)
                    print("uploaded", rel, flush=True)
            uploads.append((src, dest, mode))
        else:
            if not local.is_file():
                print(f"skip {name}: {local} not found", file=sys.stderr)
                continue
            data = local.read_bytes().replace(b"\r\n", b"\n")
            remote_tmp = f"/tmp/ha-deploy/{local.name}"
            with sftp.file(remote_tmp, "wb") as fh:
                fh.write(data)
            print("uploaded", local.name, flush=True)
            uploads.append((src, dest, mode))
        for s in svcs:
            if s not in services:
                services.append(s)

    if not uploads:
        print("nothing to deploy", file=sys.stderr)
        sftp.close()
        client.close()
        sys.exit(1)

    script = build_remote_script([u for u in uploads if not u[1].endswith("/")], services)
    with sftp.file("/tmp/ha-deploy/run.sh", "w") as fh:
        fh.write(script)
    sftp.chmod("/tmp/ha-deploy/run.sh", 0o755)
    sftp.close()

    _stdin, stdout, stderr = client.exec_command(
        f"echo {args.password} | sudo -S -p '' bash /tmp/ha-deploy/run.sh", timeout=120
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out[-4000:])
    lines = [l for l in err.splitlines() if "password" not in l.lower()]
    if lines:
        print("STDERR:\n" + "\n".join(lines)[-2500:])
    print("exit", code)
    client.close()
    if code != 0 or "DEPLOY_OK" not in out:
        sys.exit(1)


def _mkdir_p(sftp: "paramiko.SFTPClient", remote_dir: str) -> None:
    parts = remote_dir.strip("/").split("/")
    path = ""
    for part in parts:
        path += "/" + part
        try:
            sftp.mkdir(path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
