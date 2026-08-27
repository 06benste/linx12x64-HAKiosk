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
import re
import subprocess
import sys
import tarfile
import tempfile
import threading
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


STEP_RE = re.compile(r"^== (\d+)/(\d+):")


def _run_streaming(
    cmd: list[str], *, status_cb, log_path: pathlib.Path, timeout: float, env: dict | None = None,
) -> tuple[int, bool, str, list[int] | None]:
    """Run cmd with merged stdout+stderr streamed line-by-line into log_path
    and, throttled to 2/sec, into status_cb(tail, step) — so a poller can
    show live progress instead of a silent multi-minute black box (this is
    what install.sh/apt-get upgrade both were before: subprocess.run()
    capturing everything and only surfacing it after the fact).

    step is [n, total] parsed from the most recent "== n/total: ..." marker
    seen in the output (install.sh prints these; apt output has none, so it
    stays None there) — kept as its own field rather than something the
    caller re-parses from the tail text, since the marker line can scroll
    out of the tail window on a chatty step while still being the most
    recent one seen.

    A background timer kills the process after `timeout` even if it's
    produced no output at all — a hang with no output would never trip a
    plain "check elapsed time between lines" loop, since that only gets a
    chance to run when a new line actually arrives.

    Returns (returncode, timed_out, log_tail, step).
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
        )
    except OSError as exc:
        return 1, False, f"couldn't start: {exc}", None

    timed_out = {"flag": False}

    def _kill() -> None:
        timed_out["flag"] = True
        proc.kill()

    timer = threading.Timer(timeout, _kill)
    timer.start()
    tail: list[str] = []
    step: list[int] | None = None
    last_flush = 0.0
    try:
        with log_path.open("a", encoding="utf-8") as lf:
            for line in proc.stdout:
                line = line.rstrip("\n")
                lf.write(line + "\n")
                tail.append(line)
                if len(tail) > 200:
                    del tail[: len(tail) - 200]
                m = STEP_RE.match(line)
                if m:
                    step = [int(m.group(1)), int(m.group(2))]
                now = time.monotonic()
                if now - last_flush > 0.5:
                    status_cb("\n".join(tail[-40:]), step)
                    last_flush = now
        returncode = proc.wait()
    finally:
        timer.cancel()
    tail_text = "\n".join(tail[-40:])
    status_cb(tail_text, step)
    return returncode, timed_out["flag"], tail_text, step


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int):
        return False
    return pathlib.Path(f"/proc/{pid}").exists()


def _is_busy(status_file: pathlib.Path, active_states: set[str], stale_after: float = 3600) -> bool:
    """True if status_file's own last-recorded state is one of the given
    "in progress" states, recent, AND the process that wrote it is still
    alive — used to keep a kiosk-software apply and a Debian apply from
    ever running at the same time. Both eventually shell out to apt, and
    running two apt operations at once is exactly what produced the
    "Could not get lock /var/lib/apt/lists/lock" failure seen in a real log
    — a failure that then needed a manual retry.

    The pid check matters on its own, not just as a nice-to-have alongside
    stale_after: a detached apply can be killed out from under itself —
    e.g. systemd's default KillMode=control-group means restarting
    ha-kiosk-power.service (which happens on any routine deploy of
    power-api.py) kills every process in its cgroup, detached children
    included, with no chance for a Python except/finally block to run and
    record "failed". Without the liveness check, that leaves the status
    file stuck showing "in progress" — and blocking real retries via this
    exact guard — for the entire stale_after window, which for a real
    install.sh run (worth keeping long, it can legitimately take 10+
    minutes) means up to an hour."""
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("state") not in active_states:
        return False
    if not _pid_alive(data.get("pid")):
        return False
    return (time.time() - (data.get("ts") or 0)) < stale_after


APPLY_ACTIVE_STATES = {"starting", "checking", "downloading", "extracting", "installing"}
OS_APPLY_ACTIVE_STATES = {"starting", "updating", "upgrading"}


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
        _write_json(UPDATE_STATUS_FILE, {"state": state, "ts": time.time(), "pid": os.getpid(), **extra})

    if _is_busy(UPDATE_STATUS_FILE, APPLY_ACTIVE_STATES):
        status("failed", message="An update is already in progress")
        return
    if _is_busy(OS_UPDATE_STATUS_FILE, OS_APPLY_ACTIVE_STATES):
        status("failed", message="A Debian package update is running — try again once it finishes")
        return

    try:
        _cmd_apply_inner(include_camera, status)
    except Exception as exc:  # noqa: BLE001
        # Safety net: without this, any bug/unexpected exception here would
        # crash the process silently and leave the status file stuck
        # showing "in progress" forever (the exact stuck-forever symptom
        # this whole function's guard above exists to prevent triggering
        # for *other* runs — this half covers this run's own crashes).
        _log(UPDATE_LOG, f"apply crashed: {exc}")
        status("failed", message=f"Update crashed: {exc}")


def _cmd_apply_inner(include_camera: bool, status) -> None:
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

        status("installing", version=tag, log="", step=None)
        env = os.environ.copy()
        if not include_camera:
            env["SKIP_CAMERA"] = "1"
        _log(UPDATE_LOG, f"running install.sh (include_camera={include_camera})")
        returncode, timed_out, log_tail, step = _run_streaming(
            ["bash", str(install_sh)],
            status_cb=lambda tail, step: status("installing", version=tag, log=tail, step=step),
            log_path=UPDATE_LOG,
            timeout=1800,
            env=env,
        )
        if timed_out:
            status(
                "failed",
                message="Install step timed out — try again, or include_camera=false if it was rebuilding the camera driver",
                log=log_tail, step=step,
            )
            return
        if returncode != 0:
            status("failed", message=f"install.sh exited {returncode} — see {UPDATE_LOG}", log=log_tail, step=step)
            return

    VERSION_FILE.write_text(tag + "\n", encoding="utf-8")
    _merge_update_available("kiosk", {"ok": True, "current": tag, "latest": tag, "update_available": False, "notes": "", "published_at": ""})
    status("done", version=tag, message=f"Updated to {tag}")
    # Give the Updates tab's poll (every 3s) a chance to actually render
    # "done" before the display reloads out from under it — this restart
    # kills and relaunches the very Chromium tab showing that status, so
    # without this pause the update visibly succeeds but nobody ever sees
    # confirmation of that, which was leading to people re-running it
    # "just in case" it hadn't worked.
    time.sleep(5)
    _log(UPDATE_LOG, f"updated to {tag}, restarting kiosk session")
    subprocess.run(["systemctl", "restart", "getty@tty1.service"], check=False)


def cmd_os_check() -> None:
    if _is_busy(UPDATE_STATUS_FILE, APPLY_ACTIVE_STATES) or _is_busy(OS_UPDATE_STATUS_FILE, OS_APPLY_ACTIVE_STATES):
        # apt-get update also takes the apt lock — skip rather than collide
        # with an apply already using it (this is what produced "Could not
        # get lock /var/lib/apt/lists/lock" before this guard existed). The
        # daily timer's next run, or a manual re-check, picks it up fine.
        print(json.dumps({"ok": False, "error": "An update is already in progress — try again shortly"}))
        return
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
        _write_json(OS_UPDATE_STATUS_FILE, {"state": state, "ts": time.time(), "pid": os.getpid(), **extra})

    if _is_busy(OS_UPDATE_STATUS_FILE, OS_APPLY_ACTIVE_STATES):
        status("failed", message="A Debian package update is already in progress")
        return
    if _is_busy(UPDATE_STATUS_FILE, APPLY_ACTIVE_STATES):
        status("failed", message="A kiosk-software update is running — try again once it finishes")
        return

    try:
        _cmd_os_apply_inner(status)
    except Exception as exc:  # noqa: BLE001
        # Same safety net as cmd_apply — see its comment. This path is the
        # one that was actually observed stuck: a plain subprocess.run()
        # apt-get call with no try/except around it raised uncaught (e.g.
        # subprocess.TimeoutExpired while Debian's own apt-daily.timer held
        # the apt lock), silently killing this process mid-run.
        _log(OS_UPDATE_LOG, f"os-apply crashed: {exc}")
        status("failed", message=f"Update crashed: {exc}")


def _cmd_os_apply_inner(status) -> None:
    before_kernel = subprocess.run(
        ["uname", "-r"], capture_output=True, text=True
    ).stdout.strip()

    status("updating")
    _log(OS_UPDATE_LOG, "apt-get update")
    try:
        proc = subprocess.run(["apt-get", "update", "-qq"], capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        # Debian's own apt-daily.timer/apt-daily-upgrade.timer run
        # independently of anything here and can hold the apt lock for a
        # while — this used to raise straight through cmd_os_apply
        # uncaught, killing it with no "failed" status ever written.
        _log(OS_UPDATE_LOG, "apt-get update timed out (apt lock busy?)")
        status("failed", message="Couldn't refresh the package index — the system's own automatic update may be running, try again shortly")
        return
    _log(OS_UPDATE_LOG, proc.stdout[-2000:] + proc.stderr[-1000:])
    if proc.returncode != 0:
        status("failed", message="apt-get update failed")
        return

    status("upgrading", log="")
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    # Deliberately `upgrade`, not `full-upgrade`/`dist-upgrade` — never
    # removes or newly pulls in packages, just upgrades what's already
    # installed. This tablet's GPU/camera/audio stack is all fragile,
    # hand-tuned, hardware-specific software; a conservative package
    # upgrade is much less likely to disturb any of it than a full upgrade.
    returncode, timed_out, log_tail, _step = _run_streaming(
        ["apt-get", "upgrade", "-y"],
        status_cb=lambda tail, _step: status("upgrading", log=tail),
        log_path=OS_UPDATE_LOG,
        timeout=1800,
        env=env,
    )
    if timed_out:
        status("failed", message="Upgrade timed out — try again", log=log_tail)
        return
    if returncode != 0:
        status("failed", message=f"apt-get upgrade exited {returncode} — see {OS_UPDATE_LOG}", log=log_tail)
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
