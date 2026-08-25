#!/usr/bin/env python3
"""Tablet-side self-update worker: checks/pulls this project's own GitHub
releases, and separately checks/applies Debian package upgrades.

Invoked by power-api.py — `check`/`os-check` run synchronously (a single
fast HTTP call), `apply`/`os-apply` are launched detached (they can take
minutes) and report progress via a status JSON file power-api.py's
/update-status and /os-update-status endpoints read back. Kept as its own
script rather than inline in power-api.py so a long-running apply doesn't
block the API process, and so it's runnable/testable standalone over SSH.

Usage:
    self-update.py check
    self-update.py apply [--include-camera]
    self-update.py os-check
    self-update.py os-apply
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

INSTALL = pathlib.Path("/opt/ha-kiosk")
VERSION_FILE = INSTALL / "version"
UPDATE_STATUS_FILE = INSTALL / "update-status.json"
OS_UPDATE_STATUS_FILE = INSTALL / "os-update-status.json"
# Merged { "kiosk": {...}, "os": {...}, "checked_at": ... } cache that the
# power drawer's notification bubble reads (via power-api.py's
# /update-available) — written by every successful `check`/`os-check`, not
# just the daily timer, so a manual "Check for updates" tap and applying an
# update both clear/refresh the bubble immediately instead of waiting for
# the next scheduled check.
UPDATE_AVAILABLE_FILE = INSTALL / "update-available.json"
LOG_DIR = INSTALL / "logs"
UPDATE_LOG = LOG_DIR / "self-update.log"
OS_UPDATE_LOG = LOG_DIR / "os-update.log"

GITHUB_REPO = "06benste/linx12x64-HAKiosk"
RELEASES_LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    # GitHub's API rejects requests with no User-Agent at all.
    "User-Agent": "linx-ha-kiosk-self-update",
}


def current_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _write_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _log(path: pathlib.Path, msg: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    print(msg, flush=True)


def fetch_latest_release() -> dict:
    req = urllib.request.Request(RELEASES_LATEST_URL, headers=GITHUB_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _merge_update_available(section: str, data: dict) -> None:
    try:
        existing = json.loads(UPDATE_AVAILABLE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = {}
    existing[section] = data
    existing["checked_at"] = time.time()
    _write_json(UPDATE_AVAILABLE_FILE, existing)


def cmd_check() -> None:
    current = current_version()
    try:
        rel = fetch_latest_release()
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        # Deliberately not merged into UPDATE_AVAILABLE_FILE — a transient
        # network blip shouldn't flip a real "update available" badge off.
        print(json.dumps({"ok": False, "error": str(exc), "current": current}))
        return
    latest = rel.get("tag_name") or "unknown"
    result = {
        "ok": True,
        "current": current,
        "latest": latest,
        "update_available": latest != current and latest != "unknown",
        "notes": rel.get("body") or "",
        "published_at": rel.get("published_at") or "",
    }
    _merge_update_available("kiosk", result)
    print(json.dumps(result))


def cmd_apply(include_camera: bool) -> None:
    def status(state: str, **extra: object) -> None:
        _write_json(UPDATE_STATUS_FILE, {"state": state, "ts": time.time(), **extra})

    status("checking")
    try:
        rel = fetch_latest_release()
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        _log(UPDATE_LOG, f"check failed: {exc}")
        status("failed", message=f"Couldn't reach GitHub: {exc}")
        return

    tag = rel.get("tag_name") or ""
    tarball_url = rel.get("tarball_url") or ""
    if not tag or not tarball_url:
        status("failed", message="Release metadata missing tag/tarball URL")
        return

    with tempfile.TemporaryDirectory(prefix="ha-kiosk-update-") as tmp:
        tmp_path = pathlib.Path(tmp)
        archive = tmp_path / "release.tar.gz"

        status("downloading", version=tag)
        _log(UPDATE_LOG, f"downloading {tag} from {tarball_url}")
        proc = subprocess.run(
            ["curl", "-fsSL", "-o", str(archive), tarball_url],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0 or not archive.exists():
            _log(UPDATE_LOG, f"download failed: {proc.stderr.strip()}")
            status("failed", message="Download failed — check network and try again")
            return

        status("extracting", version=tag)
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        try:
            with tarfile.open(archive) as tf:
                # filter="data" (Python 3.12+) rejects path-traversal/device
                # entries etc — cheap hardening for something that runs as
                # root unattended, even though the source is our own repo.
                if sys.version_info >= (3, 12):
                    tf.extractall(extract_dir, filter="data")
                else:
                    tf.extractall(extract_dir)
        except Exception as exc:  # noqa: BLE001
            _log(UPDATE_LOG, f"extract failed: {exc}")
            status("failed", message=f"Couldn't extract the release archive: {exc}")
            return

        subdirs = [p for p in extract_dir.iterdir() if p.is_dir()]
        if len(subdirs) != 1:
            _log(UPDATE_LOG, f"unexpected archive layout: {[p.name for p in subdirs]}")
            status("failed", message="Unexpected release archive layout")
            return
        src_root = subdirs[0]
        install_sh = src_root / "scripts" / "install.sh"
        if not install_sh.exists():
            status("failed", message="scripts/install.sh missing from release archive")
            return

        status("installing", version=tag)
        env = os.environ.copy()
        if not include_camera:
            env["SKIP_CAMERA"] = "1"
        _log(UPDATE_LOG, f"running install.sh (include_camera={include_camera})")
        try:
            proc = subprocess.run(
                ["bash", str(install_sh)],
                capture_output=True, text=True, timeout=1800, env=env,
            )
        except subprocess.TimeoutExpired:
            _log(UPDATE_LOG, "install.sh timed out after 30 minutes")
            status("failed", message="Install step timed out — try again, or include_camera=false if it was rebuilding the camera driver")
            return
        _log(UPDATE_LOG, proc.stdout[-4000:])
        if proc.stderr:
            _log(UPDATE_LOG, "stderr: " + proc.stderr[-2000:])
        if proc.returncode != 0:
            status("failed", message=f"install.sh exited {proc.returncode} — see {UPDATE_LOG}")
            return

    VERSION_FILE.write_text(tag + "\n", encoding="utf-8")
    _merge_update_available("kiosk", {"ok": True, "current": tag, "latest": tag, "update_available": False, "notes": "", "published_at": ""})
    _log(UPDATE_LOG, f"updated to {tag}, restarting kiosk session")
    subprocess.run(["systemctl", "restart", "getty@tty1.service"], check=False)
    status("done", version=tag, message=f"Updated to {tag}")


def cmd_os_check() -> None:
    proc = subprocess.run(["apt-get", "update", "-qq"], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        # As in cmd_check: don't touch UPDATE_AVAILABLE_FILE on failure.
        print(json.dumps({"ok": False, "error": proc.stderr.strip()[-500:]}))
        return
    proc2 = subprocess.run(["apt", "list", "--upgradable"], capture_output=True, text=True, timeout=60)
    lines = [
        l for l in proc2.stdout.splitlines()
        if l.strip() and "/" in l and not l.startswith("Listing")
    ]
    packages = [l.split("/", 1)[0] for l in lines]
    result = {
        "ok": True,
        "upgradable_count": len(lines),
        "packages": packages,
        "update_available": len(lines) > 0,
    }
    _merge_update_available("os", result)
    print(json.dumps(result))


def cmd_os_apply() -> None:
    def status(state: str, **extra: object) -> None:
        _write_json(OS_UPDATE_STATUS_FILE, {"state": state, "ts": time.time(), **extra})

    before_kernel = subprocess.run(
        ["uname", "-r"], capture_output=True, text=True
    ).stdout.strip()

    status("updating")
    _log(OS_UPDATE_LOG, "apt-get update")
    proc = subprocess.run(["apt-get", "update", "-qq"], capture_output=True, text=True, timeout=180)
    _log(OS_UPDATE_LOG, proc.stdout[-2000:] + proc.stderr[-1000:])
    if proc.returncode != 0:
        status("failed", message="apt-get update failed")
        return

    status("upgrading")
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    # Deliberately `upgrade`, not `full-upgrade`/`dist-upgrade` — never
    # removes or newly pulls in packages, just upgrades what's already
    # installed. This tablet's GPU/camera/audio stack is all fragile,
    # hand-tuned, hardware-specific software; a conservative package
    # upgrade is much less likely to disturb any of it than a full upgrade.
    try:
        proc = subprocess.run(
            ["apt-get", "upgrade", "-y"], capture_output=True, text=True, timeout=1800, env=env,
        )
    except subprocess.TimeoutExpired:
        _log(OS_UPDATE_LOG, "apt-get upgrade timed out after 30 minutes")
        status("failed", message="Upgrade timed out — try again")
        return
    _log(OS_UPDATE_LOG, proc.stdout[-4000:])
    if proc.stderr:
        _log(OS_UPDATE_LOG, "stderr: " + proc.stderr[-2000:])
    if proc.returncode != 0:
        status("failed", message=f"apt-get upgrade exited {proc.returncode} — see {OS_UPDATE_LOG}")
        return

    newest_kernel_proc = subprocess.run(
        "dpkg -l 'linux-image-*' | awk '/^ii/{print $2}' | sort -V | tail -1",
        shell=True, capture_output=True, text=True,
    )
    newest_kernel_pkg = newest_kernel_proc.stdout.strip()
    # A kernel bump needs a reboot to take effect. DKMS's own postinst hook
    # (registered by 08-install-camera.sh's `dkms add`) should rebuild the
    # atomisp module for the new kernel automatically, same as any other
    # DKMS module — not independently verified on this hardware.
    reboot_recommended = bool(newest_kernel_pkg) and before_kernel not in newest_kernel_pkg

    _merge_update_available("os", {"ok": True, "upgradable_count": 0, "packages": [], "update_available": False})
    status("done", message="Debian packages updated", reboot_recommended=reboot_recommended)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--include-camera", action="store_true")
    sub.add_parser("os-check")
    sub.add_parser("os-apply")
    args = ap.parse_args()

    if args.cmd == "check":
        cmd_check()
    elif args.cmd == "apply":
        cmd_apply(args.include_camera)
    elif args.cmd == "os-check":
        cmd_os_check()
    elif args.cmd == "os-apply":
        cmd_os_apply()


if __name__ == "__main__":
    main()
