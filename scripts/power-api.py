#!/usr/bin/env python3
"""Localhost-only control API for the HA kiosk drawer."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

HOST = os.environ.get("KIOSK_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("KIOSK_API_PORT", "17823"))
# Requests from the tablet itself (drawer, ha-kiosk-mqtt.py) are always
# exempt via _client_is_local() below, regardless of any of this — a token
# only ever gates *other* machines on the LAN. 07-power-drawer.sh generates
# /opt/ha-kiosk/api.token on install, which is enough on its own to start
# enforcing auth for non-local callers (e.g. Home Assistant's REST sensors);
# KIOSK_API_TOKEN can override it for a specific run without touching the
# file. Delete the token file (and don't set the env var) to go back to the
# old "open to the whole trusted LAN" behavior.
TOKEN_FILE = pathlib.Path("/opt/ha-kiosk/api.token")
API_TOKEN = os.environ.get("KIOSK_API_TOKEN", "").strip()
if not API_TOKEN and TOKEN_FILE.exists():
    API_TOKEN = TOKEN_FILE.read_text(encoding="utf-8").strip()
KIOSK_USER = "kioskuser"
KIOSK_HOME = pathlib.Path(f"/home/{KIOSK_USER}")
INSTALL_ROOT = pathlib.Path("/opt/ha-kiosk")
XAUTH = KIOSK_HOME / ".Xauthority"
BLANK_FLAG = INSTALL_ROOT / "config" / "display_blanked"
ROTATION_FILE = INSTALL_ROOT / "config" / "rotation"
CAMERA_POWER_FILE = INSTALL_ROOT / "config" / "camera_power"
CAMERA_STREAM_UNIT = "ha-kiosk-camera-stream.service"
CHGLED_STATE_FILE = INSTALL_ROOT / "config" / "chgled"
# AXP288 PMIC: bus/address confirmed live on real hardware (i2c-INT33F4:00
# resolves to bus 6; 0x34 matches the "XPower AXP288 PMIC (i2c addr 0x34)"
# dmesg line every AtomISP boot already prints). REG32H bits 5,4,3 are the
# CHGLED pin's pattern + control-source bits (AXP288C datasheet §9.4.4) —
# not exposed via ACPI or the kernel's power_supply driver on this board
# (confirmed: empty /sys/class/leds, no LED-related ACPI device in the
# decoded DSDT/SSDTs), so a direct i2c-dev register write is the only
# control path that exists. Validated on real hardware: forcing bits 5,4,3
# to 0 (Hi-Z, manual mode) turns the LED off with zero effect on charging
# itself (current/voltage/status tracked normally throughout a 20s test).
CHGLED_I2C_BUS = 6
CHGLED_I2C_ADDR = "0x34"
CHGLED_REG = "0x32"
CHGLED_BITS_MASK = 0b0011_1000  # bits 5,4,3
CHGLED_CLEAR_MASK = 0xFF & ~CHGLED_BITS_MASK  # 0xC7 — AND-mask to zero just those bits


def run(cmd: list[str], timeout: float = 8, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def x_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DISPLAY"] = ":0"
    if XAUTH.exists():
        env["XAUTHORITY"] = str(XAUTH)
    env["HOME"] = str(KIOSK_HOME)
    env["USER"] = KIOSK_USER
    return env


def run_user(cmd: list[str], timeout: float = 8) -> subprocess.CompletedProcess[str]:
    # Prefer running as kioskuser for X11 tools
    full = ["runuser", "-u", KIOSK_USER, "--", *cmd]
    return run(full, timeout=timeout, env=x_env())


def backlight_path() -> pathlib.Path | None:
    root = pathlib.Path("/sys/class/backlight")
    if not root.exists():
        return None
    dirs = sorted(root.iterdir())
    return dirs[0] if dirs else None


def get_brightness() -> dict[str, Any]:
    bl = backlight_path()
    if not bl:
        return {"supported": False, "percent": None, "raw": None, "max": None}
    try:
        cur = int((bl / "brightness").read_text().strip())
        mx = int((bl / "max_brightness").read_text().strip())
        pct = int(round(100.0 * cur / mx)) if mx else 0
        return {"supported": True, "percent": pct, "raw": cur, "max": mx, "device": bl.name}
    except Exception as exc:  # noqa: BLE001
        return {"supported": False, "error": str(exc)}


def set_brightness_percent(percent: int) -> dict[str, Any]:
    bl = backlight_path()
    if not bl:
        raise RuntimeError("No backlight device")
    mx = int((bl / "max_brightness").read_text().strip())
    percent = max(1, min(100, int(percent)))  # keep at least 1% so panel isn't "dead"
    val = max(1, min(mx, int(round(mx * percent / 100.0))))
    (bl / "brightness").write_text(str(val))
    return get_brightness()


def adjust_brightness(delta: int) -> dict[str, Any]:
    cur = get_brightness()
    if not cur.get("supported"):
        raise RuntimeError("Brightness not supported")
    return set_brightness_percent(int(cur["percent"]) + int(delta))


def ha_url() -> str:
    p = INSTALL_ROOT / "url"
    if p.exists():
        return p.read_text().strip()
    return ""


def ha_reachable() -> dict[str, Any]:
    url = ha_url()
    if not url:
        return {"ok": False, "error": "not configured", "url": ""}
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return {"ok": True, "status": resp.status, "url": url}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "url": url}


def wifi_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "iface": None,
        "ssid": None,
        "signal": None,
        "quality": None,
        "level_dbm": None,
        "ip": None,
    }
    # IP
    ip_out = run(["ip", "-4", "-o", "addr", "show", "scope", "global"])
    for line in ip_out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1].startswith("wl"):
            info["iface"] = parts[1]
            info["ip"] = parts[3].split("/")[0]
            break
    if not info["ip"]:
        for line in ip_out.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                info["iface"] = parts[1]
                info["ip"] = parts[3].split("/")[0]
                break
    # SSID / signal via nmcli
    nm = run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,DEVICE", "dev", "wifi"])
    for line in nm.stdout.splitlines():
        # ACTIVE:SSID:SIGNAL:DEVICE  (SSID may contain escaped colons)
        if not line.startswith("yes:"):
            continue
        rest = line[4:]
        # split from right: DEVICE, SIGNAL, SSID...
        parts = rest.rsplit(":", 2)
        if len(parts) == 3:
            info["ssid"] = parts[0].replace("\\:", ":") or None
            try:
                info["signal"] = int(parts[1]) if parts[1] else None
            except ValueError:
                info["signal"] = parts[1] or None
            info["iface"] = parts[2] or info["iface"]
        break
    if not info["ssid"] and info["iface"]:
        conn = run(["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", info["iface"]])
        name = conn.stdout.strip()
        if name and name != "--":
            info["ssid"] = name
    if not info["ssid"]:
        iw = run(["iwgetid", "-r"])
        if iw.returncode == 0 and iw.stdout.strip():
            info["ssid"] = iw.stdout.strip()
    if info["signal"] is None and info["iface"]:
        sig = run(["nmcli", "-g", "GENERAL.SIGNAL", "device", "show", info["iface"]])
        try:
            info["signal"] = int(sig.stdout.strip())
        except ValueError:
            pass

    # Quality / dBm from /proc/net/wireless
    try:
        for line in pathlib.Path("/proc/net/wireless").read_text().splitlines():
            if ":" not in line:
                continue
            iface, rest = line.split(":", 1)
            iface = iface.strip()
            if info["iface"] and iface != info["iface"]:
                continue
            if not iface.startswith("wl") and iface != (info["iface"] or ""):
                continue
            cols = rest.split()
            # status link level noise ...
            if len(cols) >= 3:
                try:
                    link = float(cols[1].rstrip("."))
                    level = float(cols[2].rstrip("."))
                    info["quality"] = int(round(link))
                    # Convert to rough percent if nmcli signal missing (link often 0-70)
                    if info["signal"] is None and link > 0:
                        info["signal"] = max(0, min(100, int(round(link * 100 / 70))))
                    info["level_dbm"] = int(round(level))
                    if not info["iface"]:
                        info["iface"] = iface
                except ValueError:
                    pass
            break
    except Exception:
        pass
    return info


def thermal_info() -> dict[str, Any]:
    """CPU / SoC temperatures in °C."""
    info: dict[str, Any] = {
        "cpu_c": None,
        "soc_c": None,
        "acpi_c": None,
        "zones": {},
    }
    # thermal zones
    root = pathlib.Path("/sys/class/thermal")
    if root.exists():
        for zone in sorted(root.glob("thermal_zone*")):
            try:
                ztype = (zone / "type").read_text().strip()
                temp_mC = int((zone / "temp").read_text().strip())
                temp_c = round(temp_mC / 1000, 1)
                info["zones"][ztype] = temp_c
                low = ztype.lower()
                if "soc_dts0" in low or low == "soc_dts0":
                    info["soc_c"] = temp_c
                if low == "acpitz" and info["acpi_c"] is None:
                    info["acpi_c"] = temp_c
            except Exception:
                continue

    # coretemp package / core max
    hwmon = pathlib.Path("/sys/class/hwmon")
    if hwmon.exists():
        for h in hwmon.glob("hwmon*"):
            try:
                name = (h / "name").read_text().strip()
            except Exception:
                continue
            if name == "coretemp":
                temps = []
                for tf in h.glob("temp*_input"):
                    try:
                        temps.append(int(tf.read_text().strip()) / 1000)
                    except Exception:
                        pass
                if temps:
                    info["cpu_c"] = round(max(temps), 1)
            elif name == "soc_dts0" and info["soc_c"] is None:
                try:
                    info["soc_c"] = round(int((h / "temp1_input").read_text().strip()) / 1000, 1)
                except Exception:
                    pass
            elif name == "acpitz" and info["acpi_c"] is None:
                try:
                    info["acpi_c"] = round(int((h / "temp1_input").read_text().strip()) / 1000, 1)
                except Exception:
                    pass

    if info["soc_c"] is None:
        info["soc_c"] = info["zones"].get("soc_dts0") or info["zones"].get("soc_dts1")
    if info["cpu_c"] is None:
        # fallback: PNIT / highest reasonable zone
        for key in ("PNIT", "STR0", "acpitz"):
            if key in info["zones"]:
                info["cpu_c"] = info["zones"][key]
                break
    return info


def disk_info(path: str = "/") -> dict[str, Any]:
    """Filesystem usage for root (or given path)."""
    info: dict[str, Any] = {
        "path": path,
        "total_gb": None,
        "used_gb": None,
        "free_gb": None,
        "used_percent": None,
    }
    try:
        st = os.statvfs(path)
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bavail
        used = total - free
        info["total_gb"] = round(total / (1024**3), 2)
        info["used_gb"] = round(used / (1024**3), 2)
        info["free_gb"] = round(free / (1024**3), 2)
        info["used_percent"] = int(round(100 * used / total)) if total else None
    except Exception:
        pass
    return info


def uptime_info() -> dict[str, Any]:
    try:
        up = float(pathlib.Path("/proc/uptime").read_text().split()[0])
    except Exception:  # noqa: BLE001
        up = None
    load = None
    try:
        load = [float(x) for x in pathlib.Path("/proc/loadavg").read_text().split()[:3]]
    except Exception:  # noqa: BLE001
        pass
    mem = {}
    try:
        data = pathlib.Path("/proc/meminfo").read_text()
        vals = {}
        for line in data.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                vals[k] = int(v.strip().split()[0])
        total = vals.get("MemTotal", 0)
        avail = vals.get("MemAvailable", 0)
        mem = {
            "total_mb": round(total / 1024),
            "available_mb": round(avail / 1024),
            "used_pct": int(round(100 * (1 - (avail / total)))) if total else None,
        }
    except Exception:  # noqa: BLE001
        pass
    return {"seconds": up, "load": load, "memory": mem}


def rotation_info() -> str:
    """Current rotation, as last set via the /rotate action. Applied by the
    kiosk extension as a full-page CSS transform (see chromium-extension/
    rotation.js) rather than xrandr — the default kiosk is cage/Wayland,
    which runs no X server at all, so xrandr has nothing to talk to."""
    try:
        val = ROTATION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "normal"
    return val if val in ("normal", "left", "right", "inverted") else "normal"


AUTO_ROTATE_UNIT = "ha-kiosk-auto-rotate.service"


def auto_rotate_info() -> dict[str, Any]:
    """Whether scripts/auto-rotate.py (accelerometer -> /rotate) is running.
    Its enabled/active systemd state *is* the persisted setting — no
    separate state file, same as asking systemd is the single source of
    truth rather than risking it disagreeing with a file on disk."""
    installed = pathlib.Path(f"/etc/systemd/system/{AUTO_ROTATE_UNIT}").exists()
    if not installed:
        return {"on": False, "installed": False}
    enabled = run(["systemctl", "is-enabled", AUTO_ROTATE_UNIT]).stdout.strip() == "enabled"
    active = run(["systemctl", "is-active", AUTO_ROTATE_UNIT]).stdout.strip() == "active"
    return {"on": enabled and active, "installed": True}


def set_auto_rotate(on: bool) -> dict[str, Any]:
    on = bool(on)
    if on:
        run(["systemctl", "enable", "--now", AUTO_ROTATE_UNIT], timeout=15)
    else:
        run(["systemctl", "disable", "--now", AUTO_ROTATE_UNIT], timeout=15)
    return {"on": on, "message": f"Auto-rotate {'on' if on else 'off'}"}


def detach(cmd: list[str]) -> None:
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


SELF_UPDATE_SCRIPT = "/opt/ha-kiosk/scripts/self-update.py"
UPDATE_STATUS_FILE = INSTALL_ROOT / "update-status.json"
OS_UPDATE_STATUS_FILE = INSTALL_ROOT / "os-update-status.json"
# Written by self-update.py's check/os-check (both the daily timer and the
# Updates tab's manual "Check" buttons) — the power drawer polls this cheap
# read-only endpoint to decide whether to show its notification bubble,
# without triggering a GitHub/apt check itself.
UPDATE_AVAILABLE_FILE = INSTALL_ROOT / "update-available.json"


def _read_status_file(path: pathlib.Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "idle"}


def _reset_status_file(path: pathlib.Path, state: str) -> None:
    """Written synchronously, before the real work is even detached — closes
    a real race where the Updates tab's poll fires immediately after the
    apply POST resolves and can read stale state left over from the
    *previous* run (done/failed/idle) before the new detached process gets
    a chance to write anything of its own. That stale read was being
    displayed as this run's outcome — showing an instant misleading "done"
    (reboot banner and all) or "failed", which also stops polling and
    re-enables the button, inviting another press while the real update
    kept running unobserved underneath it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": state, "ts": time.time()}), encoding="utf-8")


def update_check() -> dict[str, Any]:
    """Synchronous — a single GitHub API call, self-update.py's own `check`
    subcommand handles the HTTP request and JSON shape."""
    proc = run(["python3", SELF_UPDATE_SCRIPT, "check"], timeout=20)
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {"ok": False, "error": proc.stderr.strip() or "self-update check failed"}


def update_apply(include_camera: bool) -> dict[str, Any]:
    """Detached — can take minutes (download + re-run install.sh). The
    Updates tab polls update_status()/os_update_status() for progress."""
    _reset_status_file(UPDATE_STATUS_FILE, "starting")
    cmd = ["python3", SELF_UPDATE_SCRIPT, "apply"]
    if include_camera:
        cmd.append("--include-camera")
    detach(cmd)
    return {"message": "Update started"}


def update_status() -> dict[str, Any]:
    return _read_status_file(UPDATE_STATUS_FILE)


def update_available_summary() -> dict[str, Any]:
    try:
        return json.loads(UPDATE_AVAILABLE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def os_update_check() -> dict[str, Any]:
    proc = run(["python3", SELF_UPDATE_SCRIPT, "os-check"], timeout=150)
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return {"ok": False, "error": proc.stderr.strip() or "os-check failed"}


def os_update_apply() -> dict[str, Any]:
    _reset_status_file(OS_UPDATE_STATUS_FILE, "starting")
    detach(["python3", SELF_UPDATE_SCRIPT, "os-apply"])
    return {"message": "Debian package update started"}


def os_update_status() -> dict[str, Any]:
    return _read_status_file(OS_UPDATE_STATUS_FILE)


def restart_kiosk() -> str:
    """Restart whichever kiosk mechanism is active. Default since 02-install-kiosk.sh
    is the tty1 .bash_profile launch (restart via getty@tty1.service); a
    graphical.target/tty7 systemd service is only used if something enabled it
    manually — that mechanism doesn't reliably work (see 04-fix-kiosk-autostart.sh)
    but is still supported here in case it's ever active."""
    active = run(["systemctl", "is-active", "ha-kiosk.service"]).stdout.strip()
    if active == "active":
        run(["systemctl", "restart", "ha-kiosk.service"])
        return "ha-kiosk.service"
    run(["systemctl", "restart", "getty@tty1.service"])
    return "getty@tty1.service"


def reconfigure_ha() -> None:
    """Drop the saved HA URL/credentials so the kiosk falls back to the setup wizard."""
    (INSTALL_ROOT / "url").unlink(missing_ok=True)
    (INSTALL_ROOT / "credentials.env").unlink(missing_ok=True)
    config_js = INSTALL_ROOT / "chromium-extension" / "config.js"
    config_js.parent.mkdir(parents=True, exist_ok=True)
    config_js.write_text("window.HA_KIOSK_AUTH = {};\n", encoding="utf-8")


def power_info() -> dict[str, Any]:
    """Battery + AC/USB power from AXP288 (Cherry Trail)."""
    root = pathlib.Path("/sys/class/power_supply")
    info: dict[str, Any] = {
        "supported": False,
        "plugged_in": None,
        "charging": None,
        "battery_percent": None,
        "battery_status": None,
        "voltage_v": None,
        "current_ma": None,
        "technology": None,
    }
    if not root.exists():
        return info

    # Prefer axp288_* if present, else first Battery / Mains/USB
    bat = None
    chg = None
    for d in sorted(root.iterdir()):
        tfile = d / "type"
        if not tfile.exists():
            continue
        typ = tfile.read_text().strip()
        name = d.name.lower()
        if typ == "Battery" and bat is None:
            bat = d
        if typ in ("USB", "Mains") and chg is None:
            chg = d
        if "fuel_gauge" in name:
            bat = d
        if "charger" in name:
            chg = d

    if bat is None and chg is None:
        return info

    info["supported"] = True
    try:
        if chg is not None and (chg / "online").exists():
            info["plugged_in"] = (chg / "online").read_text().strip() == "1"
        elif chg is not None and (chg / "present").exists():
            info["plugged_in"] = (chg / "present").read_text().strip() == "1"
    except Exception:
        pass

    try:
        if bat is not None:
            if (bat / "capacity").exists():
                info["battery_percent"] = int((bat / "capacity").read_text().strip())
            if (bat / "status").exists():
                info["battery_status"] = (bat / "status").read_text().strip()
            if (bat / "technology").exists():
                info["technology"] = (bat / "technology").read_text().strip()
            if (bat / "voltage_now").exists():
                info["voltage_v"] = round(int((bat / "voltage_now").read_text().strip()) / 1_000_000, 3)
            if (bat / "current_now").exists():
                info["current_ma"] = round(int((bat / "current_now").read_text().strip()) / 1000)
    except Exception:
        pass

    status = (info.get("battery_status") or "").lower()
    if status in ("charging", "full", "chargingful", "not charging"):
        # "Not charging" often means plugged in but topped up / hold
        info["charging"] = status in ("charging", "full")
    elif info.get("plugged_in") is True and status == "discharging":
        # Some AXP288 reports Discharging briefly while USB-online
        info["charging"] = False
    elif info.get("plugged_in") is True:
        info["charging"] = True
    elif info.get("plugged_in") is False:
        info["charging"] = False

    return info


def set_display_blanked(blanked: bool) -> None:
    """Blank/wake the panel via the backlight (direct sysfs), not X11 DPMS.
    DPMS/xset only work when an X server is actually running — that's true
    under the X11 fallback kiosk (05-x11-kiosk.sh) but NOT the default
    cage/Wayland kiosk, which runs no X server at all. Backlight control
    works under either, so it's what both display-off/display-on actions use.
    The flag file doubles as storage for the pre-blank brightness, so "on"
    restores exactly what it was rather than jumping to a fixed level.

    True off uses bl_power (FB_BLANK_POWERDOWN=4 / FB_BLANK_UNBLANK=0), not
    just dimming brightness to its 1% floor — that floor exists so the
    brightness *slider* can never accidentally go fully dark, but it means
    reusing plain brightness for "blank" only ever dims, never truly blanks
    (confirmed on real hardware: intel_backlight here exposes bl_power
    alongside brightness). Falls back to raw brightness=0 — bypassing
    set_brightness_percent's 1% floor directly at the sysfs level — on any
    backlight device that doesn't have bl_power."""
    BLANK_FLAG.parent.mkdir(parents=True, exist_ok=True)
    bl = backlight_path()
    bl_power = (bl / "bl_power") if bl else None
    has_bl_power = bool(bl_power and bl_power.exists())
    if blanked:
        cur = get_brightness()
        prev = cur.get("percent") if cur.get("supported") else None
        BLANK_FLAG.write_text(f"{prev if prev is not None else 80}\n", encoding="utf-8")
        try:
            os.chmod(BLANK_FLAG, 0o666)
        except OSError:
            pass
        if has_bl_power:
            bl_power.write_text("4")
        elif bl:
            (bl / "brightness").write_text("0")
    else:
        prev = 80
        if BLANK_FLAG.exists():
            try:
                prev = int(BLANK_FLAG.read_text().strip())
            except ValueError:
                pass
        BLANK_FLAG.unlink(missing_ok=True)
        if has_bl_power:
            bl_power.write_text("0")
        if get_brightness().get("supported"):
            set_brightness_percent(prev)


def display_info() -> dict[str, Any]:
    """Report whether the panel is blanked, from our own intentional-blank
    flag + current backlight level — not X11 DPMS (see set_display_blanked)."""
    flagged = BLANK_FLAG.exists()
    state = "blanked" if flagged else "on"
    return {
        "state": state,
        "blanked": flagged,
        "on": not flagged,
        "intentional": flagged,
        "brightness": get_brightness(),
    }


def load_camera_power() -> bool:
    """Persisted camera on/off state, shared with ha-kiosk-mqtt.py. Default ON."""
    if CAMERA_POWER_FILE.exists():
        val = CAMERA_POWER_FILE.read_text(encoding="utf-8").strip().lower()
        return val not in ("0", "off", "false", "no")
    return True


def save_camera_power(on: bool) -> None:
    CAMERA_POWER_FILE.parent.mkdir(parents=True, exist_ok=True)
    CAMERA_POWER_FILE.write_text("1\n" if on else "0\n", encoding="utf-8")


def set_camera_power(on: bool) -> dict[str, Any]:
    """Single source of truth for camera on/off — starts/stops the stream
    service so an off camera serves no frames at all (not just a UI hide),
    which is what makes it safe to say "no image available" while off. Both
    the on-tablet drawer and the MQTT camera switch call this via /camera
    rather than touching systemctl themselves, so the two controls can never
    disagree about whether the service should be running."""
    on = bool(on)
    save_camera_power(on)
    if on:
        run(["systemctl", "start", CAMERA_STREAM_UNIT], timeout=20)
    else:
        run(["systemctl", "stop", CAMERA_STREAM_UNIT], timeout=20)
        # Free any leftover capture processes the stream unit spawned.
        run(["pkill", "-9", "-f", "v4l2-ctl --stream"])
        run(["pkill", "-9", "-f", "camera-stream-server.py"])
    return {"on": on, "message": f"Camera {'on' if on else 'off'}"}


def camera_info() -> dict[str, Any]:
    return {"power": load_camera_power()}


def load_chgled_on() -> bool:
    """Persisted desired state for the charge indicator LED. Default ON,
    matching this hardware's own factory boot behavior (AUTO/charger-driven)
    when nothing has ever overridden it."""
    if CHGLED_STATE_FILE.exists():
        val = CHGLED_STATE_FILE.read_text(encoding="utf-8").strip().lower()
        return val not in ("0", "off", "false", "no")
    return True


def save_chgled_on(on: bool) -> None:
    CHGLED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHGLED_STATE_FILE.write_text("1\n" if on else "0\n", encoding="utf-8")


def _chgled_i2cget() -> int | None:
    r = run(["i2cget", "-y", "-f", str(CHGLED_I2C_BUS), CHGLED_I2C_ADDR, CHGLED_REG])
    if r.returncode != 0:
        return None
    try:
        return int(r.stdout.strip(), 16)
    except ValueError:
        return None


def _chgled_i2cset(value: int) -> bool:
    r = run(["i2cset", "-y", "-f", str(CHGLED_I2C_BUS), CHGLED_I2C_ADDR, CHGLED_REG, hex(value & 0xFF)])
    return r.returncode == 0


def set_chgled(on: bool) -> dict[str, Any]:
    """Only ever touches REG32H bits 5,4,3 (the CHGLED pattern + control-
    source bits) — every other bit (battery-detect enable, PWROK delay) is
    read fresh from the live register and preserved exactly, never assumed.
    ON sets bit3=1 (hands the pin back to the charger's own automatic
    state machine); OFF clears bits 5,4,3 (forces Hi-Z / manual / off).
    A raw register write like this doesn't survive a reboot on its own —
    firmware reprograms REG32H back to AUTO during early boot before Linux
    even loads — so this also persists the desired state for main() to
    re-apply on every power-api.py startup."""
    on = bool(on)
    current = _chgled_i2cget()
    if current is None:
        raise RuntimeError(
            f"could not read AXP288 REG32H over i2c (bus {CHGLED_I2C_BUS}, addr {CHGLED_I2C_ADDR}) "
            "— is i2c-dev loaded? (modprobe i2c-dev)"
        )
    new_value = (current | 0b0000_1000) if on else (current & CHGLED_CLEAR_MASK)
    if not _chgled_i2cset(new_value):
        raise RuntimeError("i2cset failed writing REG32H")
    save_chgled_on(on)
    return {"on": on, "message": f"Charge LED {'enabled' if on else 'disabled'}"}


def chgled_info() -> dict[str, Any]:
    return {"on": load_chgled_on()}


def status_payload() -> dict[str, Any]:
    host = run(["hostname"]).stdout.strip()
    return {
        "hostname": host,
        "wifi": wifi_info(),
        "uptime": uptime_info(),
        "brightness": get_brightness(),
        "power": power_info(),
        "thermal": thermal_info(),
        "disk": disk_info("/"),
        "ha": ha_reachable(),
        "rotation": rotation_info(),
        "auto_rotate": auto_rotate_info(),
        "display": display_info(),
        "camera": camera_info(),
        "chgled": chgled_info(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def handle_action(action: str, body: dict[str, Any]) -> dict[str, Any]:
    if action == "reboot":
        detach(["systemctl", "reboot"])
        return {"ok": True, "message": "Rebooting"}
    if action == "shutdown":
        detach(["systemctl", "poweroff"])
        return {"ok": True, "message": "Shutting down"}
    if action == "refresh":
        # Soft F5-reload needs xdotool talking to a real X server — only true
        # under the X11 fallback kiosk. The default cage/Wayland kiosk has no
        # X server at all, so xdotool can't find any window there. Fall back
        # to a full kiosk restart in that case — it reloads the page too,
        # just less gently (a couple seconds of blank screen).
        if run(["which", "xdotool"]).returncode == 0:
            r = run_user(["xdotool", "search", "--onlyvisible", "--class", "chromium"])
            wids = [w for w in r.stdout.split() if w.isdigit()]
            if wids:
                run_user(["xdotool", "key", "--window", wids[0], "F5"])
                return {"ok": True, "message": "Refreshing"}
        service = restart_kiosk()
        return {"ok": True, "message": "Restarting kiosk display to refresh", "service": service}
    if action == "chromium-restart":
        service = restart_kiosk()
        return {"ok": True, "message": "Restarting kiosk display", "service": service}
    if action == "reconfigure-ha":
        reconfigure_ha()
        service = restart_kiosk()
        return {"ok": True, "message": "Reconfiguring — restarting into setup", "service": service}
    if action == "clear-cache":
        # Wipe caches then restart session
        script = r"""
set -e
systemctl stop getty@tty1.service || true
pkill -u kioskuser chromium || true
sleep 1
rm -rf /opt/ha-kiosk/chromium-profile/Default/Cache \
       /opt/ha-kiosk/chromium-profile/Default/Code\ Cache \
       /opt/ha-kiosk/chromium-profile/Default/GPUCache \
       /opt/ha-kiosk/chromium-profile/ShaderCache \
       /opt/ha-kiosk/chromium-profile/GrShaderCache \
       /opt/ha-kiosk/chromium-profile/Default/Service\ Worker || true
systemctl start getty@tty1.service
"""
        detach(["bash", "-lc", script])
        return {"ok": True, "message": "Clearing cache and restarting display"}
    if action == "display-off":
        # Backlight-based blank (works under cage/Wayland or X11). The xset
        # calls below are best-effort extra DPMS power-saving for the X11
        # fallback kiosk specifically — silently no-op under the default
        # cage kiosk (no X server, xset likely isn't even installed there).
        set_display_blanked(True)
        run_user(["xset", "s", "off"])
        run_user(["xset", "+dpms"])
        run_user(["xset", "dpms", "force", "off"])
        return {"ok": True, "message": "Display off — tap Wake to restore", "display": display_info()}
    if action == "display-on":
        set_display_blanked(False)
        run_user(["xset", "dpms", "force", "on"])
        run_user(["xset", "s", "reset"])
        run_user(["xset", "-dpms"])
        run_user(["xset", "s", "noblank"])
        return {"ok": True, "message": "Display on", "display": display_info()}
    if action == "brightness":
        if "percent" in body:
            return {"ok": True, "brightness": set_brightness_percent(int(body["percent"]))}
        if "delta" in body:
            return {"ok": True, "brightness": adjust_brightness(int(body["delta"]))}
        raise RuntimeError("brightness requires percent or delta")
    if action == "rotate":
        direction = str(body.get("direction", "normal"))
        if direction not in ("normal", "left", "right", "inverted"):
            raise RuntimeError("Invalid rotation")
        # Rotation is a full-page CSS transform applied by the kiosk
        # extension (chromium-extension/rotation.js), not xrandr — the
        # default kiosk is cage/Wayland, which runs no X server at all, so
        # there'd be nothing for xrandr to talk to even if it were
        # installed. This just persists the choice for the extension to
        # read (on this call via the response, and on future page loads via
        # GET /status). No kiosk restart needed — the extension applies it
        # immediately client-side.
        ROTATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        ROTATION_FILE.write_text(direction, encoding="utf-8")
        return {
            "ok": True,
            "rotation": direction,
            "message": f"Rotated {direction}",
        }
    if action == "camera":
        if "state" in body:
            on = str(body["state"]).strip().lower() in ("on", "1", "true", "yes")
        elif "on" in body:
            on = bool(body["on"])
        else:
            raise RuntimeError("camera requires on (bool) or state (on/off)")
        return {"ok": True, **set_camera_power(on)}
    if action == "chgled":
        if "state" in body:
            on = str(body["state"]).strip().lower() in ("on", "1", "true", "yes")
        elif "on" in body:
            on = bool(body["on"])
        else:
            raise RuntimeError("chgled requires on (bool) or state (on/off)")
        return {"ok": True, **set_chgled(on)}
    if action == "auto-rotate":
        if "state" in body:
            on = str(body["state"]).strip().lower() in ("on", "1", "true", "yes")
        elif "on" in body:
            on = bool(body["on"])
        else:
            raise RuntimeError("auto-rotate requires on (bool) or state (on/off)")
        return {"ok": True, **set_auto_rotate(on)}
    if action == "night-on":
        set_brightness_percent(20)
        return {"ok": True, "message": "Night dim on", "brightness": get_brightness()}
    if action == "night-off":
        set_brightness_percent(80)
        return {"ok": True, "message": "Night dim off", "brightness": get_brightness()}
    if action == "update-check":
        return {"ok": True, **update_check()}
    if action == "update-apply":
        return {"ok": True, **update_apply(bool(body.get("include_camera")))}
    if action == "os-update-check":
        return {"ok": True, **os_update_check()}
    if action == "os-update-apply":
        return {"ok": True, **os_update_apply()}
    raise RuntimeError(f"Unknown action: {action}")


class Handler(BaseHTTPRequestHandler):
    server_version = "HaKioskPower/2.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Kiosk-Token")

    def _client_is_local(self) -> bool:
        host = self.client_address[0]
        return host in ("127.0.0.1", "::1")

    def _authorized(self) -> bool:
        # Local drawer / mqtt agent always allowed
        if self._client_is_local():
            return True
        if not API_TOKEN:
            # No token configured — allow LAN reads/writes (trusted home LAN)
            return True
        auth = self.headers.get("Authorization", "")
        token = self.headers.get("X-Kiosk-Token", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
        return token == API_TOKEN

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/health":
            self._json(200, {"ok": True})
            return
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        if path == "/status":
            try:
                self._json(200, {"ok": True, **status_payload()})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/update-status":
            self._json(200, {"ok": True, **update_status()})
            return
        if path == "/os-update-status":
            self._json(200, {"ok": True, **os_update_status()})
            return
        if path == "/update-available":
            self._json(200, {"ok": True, **update_available_summary()})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_json()
        # Allow query params too: /brightness?delta=10
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
        body = {**qs, **body}

        action = path.lstrip("/")
        # Legacy aliases
        if action in ("reboot", "shutdown", "refresh", "chromium-restart", "clear-cache",
                      "display-off", "display-on", "brightness", "rotate",
                      "night-on", "night-off", "reconfigure-ha", "camera", "chgled",
                      "auto-rotate", "update-check", "update-apply",
                      "os-update-check", "os-update-apply"):
            try:
                result = handle_action(action, body)
                self._json(200, result)
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"ok": False, "error": str(exc)})
            return
        self._json(404, {"ok": False, "error": "not found"})


def main() -> None:
    # Firmware reprograms the AXP288's CHGLED register back to its own
    # AUTO default during early boot, before Linux even loads — re-apply
    # whatever the user last chose every time this service starts, the
    # same way set_camera_power's persisted state gets re-applied on
    # ha-kiosk-mqtt.py's own startup.
    try:
        set_chgled(load_chgled_on())
    except Exception as exc:  # noqa: BLE001
        print(f"chgled startup apply failed: {exc}", flush=True)

    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"kiosk API on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
