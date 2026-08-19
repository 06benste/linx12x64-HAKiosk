#!/usr/bin/env python3
"""First-boot / reconfigure HTTP UI: sets the HA URL, optional login, and Wi-Fi.

Serves scripts/static/setup.html plus a small JSON API. kiosk-launch.sh points
Chromium here whenever /opt/ha-kiosk/url is empty; the power drawer also opens
this page (embedded) for later reconfiguration.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

# Loopback-only by default, deliberately: this API has no auth at all (it
# rewrites the tablet's HA URL/login, Wi-Fi credentials, and MQTT broker
# credentials with a plain POST), and unlike power-api.py / camera-stream
# there's no legitimate reason for another machine on the LAN to reach it —
# both callers (the drawer's overlay iframe, and kiosk-launch.sh's
# standalone first-boot page) already run in the tablet's own browser, i.e.
# against 127.0.0.1. Override only if you specifically need to drive setup
# from another device, and understand that opens config-rewrite access to
# the whole LAN.
HOST = os.environ.get("SETUP_WIZARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("SETUP_WIZARD_PORT", "17825"))
KIOSK_USER = "kioskuser"
INSTALL_ROOT = pathlib.Path("/opt/ha-kiosk")
URL_FILE = INSTALL_ROOT / "url"
CRED_FILE = INSTALL_ROOT / "credentials.env"
CONFIG_JS = INSTALL_ROOT / "chromium-extension" / "config.js"
MQTT_ENV_FILE = INSTALL_ROOT / "mqtt.env"
MQTT_UNIT = "ha-kiosk-mqtt.service"
STATIC_DIR = pathlib.Path(
    os.environ.get(
        "SETUP_WIZARD_STATIC",
        str(
            INSTALL_ROOT / "scripts" / "static"
            if (INSTALL_ROOT / "scripts" / "static" / "setup.html").exists()
            else pathlib.Path(__file__).resolve().parent / "static"
        ),
    )
)


def run(cmd: list[str], timeout: float = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def read_current_url() -> str:
    if URL_FILE.exists():
        return URL_FILE.read_text(encoding="utf-8").strip()
    return ""


def read_current_user() -> str:
    if not CRED_FILE.exists():
        return ""
    for line in CRED_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("HA_USER="):
            return line[len("HA_USER="):]
    return ""


def has_password() -> bool:
    if not CRED_FILE.exists():
        return False
    for line in CRED_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("HA_PASS=") and line[len("HA_PASS="):]:
            return True
    return False


def write_ha_config(url: str, user: str, password: str) -> None:
    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    URL_FILE.write_text(url.strip() + "\n", encoding="utf-8")

    if user and password:
        CRED_FILE.write_text(f"HA_USER={user}\nHA_PASS={password}\n", encoding="utf-8")
        os.chmod(CRED_FILE, 0o600)
    else:
        CRED_FILE.unlink(missing_ok=True)

    CONFIG_JS.parent.mkdir(parents=True, exist_ok=True)
    if user and password:
        auth = json.dumps({"user": user, "pass": password})
        CONFIG_JS.write_text(f"window.HA_KIOSK_AUTH = {auth};\n", encoding="utf-8")
    else:
        CONFIG_JS.write_text("window.HA_KIOSK_AUTH = {};\n", encoding="utf-8")
    os.chmod(CONFIG_JS, 0o600)

    run(["chown", "-R", f"{KIOSK_USER}:{KIOSK_USER}", str(INSTALL_ROOT)])


def clear_ha_config() -> None:
    URL_FILE.unlink(missing_ok=True)
    CRED_FILE.unlink(missing_ok=True)
    CONFIG_JS.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_JS.write_text("window.HA_KIOSK_AUTH = {};\n", encoding="utf-8")


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


def test_url(url: str) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return {"ok": True, "status": resp.status}
    except urllib.error.HTTPError as exc:
        # HA returns 401/redirect for unauthenticated GETs — server responded, so reachable.
        return {"ok": True, "status": exc.code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def wifi_scan() -> list[dict[str, Any]]:
    # -m multiline (one "FIELD:value" per line) instead of the default terse
    # colon-joined row — a plain `line.split(":")` on the terse form breaks as
    # soon as an SSID contains a literal colon (nmcli backslash-escapes it,
    # which a naive split doesn't know about), and silently produced zero or
    # garbled entries for any SSID like that.
    r = run(
        ["nmcli", "-t", "-m", "multiline", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"],
        timeout=20,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"nmcli exited {r.returncode}")

    seen: dict[str, dict[str, Any]] = {}
    cur: dict[str, str] = {}

    def flush() -> None:
        ssid = cur.get("SSID", "").strip()
        if not ssid:
            return
        try:
            signal = int(cur.get("SIGNAL", "0"))
        except ValueError:
            signal = 0
        secure = cur.get("SECURITY", "").strip() not in ("", "--")
        existing = seen.get(ssid)
        if existing is None or signal > existing["signal"]:
            seen[ssid] = {"ssid": ssid, "signal": signal, "secure": secure}

    for line in r.stdout.splitlines():
        if ":" not in line:
            continue
        field, _, value = line.partition(":")
        if field == "SSID" and "SSID" in cur:
            # New record starting — flush the previous one first.
            flush()
            cur = {}
        cur[field] = value
    flush()  # last record
    return sorted(seen.values(), key=lambda x: x["signal"], reverse=True)


def wifi_connect(ssid: str, password: str) -> dict[str, Any]:
    # nmcli's own "device wifi connect" tries to reuse an existing saved
    # connection profile with the same name/SSID if one is already present,
    # rather than always creating a fresh one. If that existing profile is
    # incomplete or was created some other way (e.g. by hand, by a migration
    # script, or a previous failed attempt from this same UI), reuse can
    # fail with a cryptic "802-11-wireless-security-key.mgmt: property is
    # missing" instead of just working — confirmed on real hardware.
    # Deleting any same-named profile first guarantees nmcli always builds
    # a correct one from scratch for the password we were just given.
    run(["nmcli", "connection", "delete", ssid], timeout=10)
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    r = run(cmd, timeout=30)
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout).strip() or "connection failed"}
    return {"ok": True, "message": f"Connected to {ssid}"}


def _parse_env(path: pathlib.Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def mqtt_enabled() -> bool:
    return run(["systemctl", "is-enabled", MQTT_UNIT]).stdout.strip() == "enabled"


def read_mqtt_config() -> dict[str, Any]:
    env = _parse_env(MQTT_ENV_FILE)
    return {
        "host": env.get("MQTT_HOST", ""),
        "port": env.get("MQTT_PORT", "1883"),
        "user": env.get("MQTT_USER", ""),
        "has_password": bool(env.get("MQTT_PASSWORD")),
        "enabled": mqtt_enabled(),
    }


def write_mqtt_config(host: str, port: str, user: str, password: str) -> None:
    """Merge into mqtt.env, preserving any keys the UI doesn't expose
    (camera-stream/screenshot tunables from mqtt.env.example) instead of
    clobbering them. Password is only overwritten when a new one is typed —
    an unchanged blank field keeps whatever was already saved, same pattern
    as the HA tab's password field."""
    # Only the connection fields below are UI-managed; ha-kiosk-mqtt.py has
    # its own built-in defaults for everything else (camera-stream/
    # screenshot tunables from mqtt.env.example), so there's nothing to
    # seed here beyond what's already in the file.
    env = _parse_env(MQTT_ENV_FILE)
    env["MQTT_HOST"] = host
    env["MQTT_PORT"] = port or "1883"
    env["MQTT_USER"] = user
    if password:
        env["MQTT_PASSWORD"] = password
    env.setdefault("MQTT_INTERVAL", "15")

    MQTT_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in env.items()]
    MQTT_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(MQTT_ENV_FILE, 0o600)
    run(["chown", f"{KIOSK_USER}:{KIOSK_USER}", str(MQTT_ENV_FILE)])


def set_mqtt_enabled(enabled: bool) -> None:
    if enabled:
        run(["systemctl", "enable", "--now", MQTT_UNIT], timeout=20)
    else:
        run(["systemctl", "disable", "--now", MQTT_UNIT], timeout=20)


def test_mqtt(host: str, port: int, user: str, password: str) -> dict[str, Any]:
    if not host:
        return {"ok": False, "error": "Broker host required"}
    try:
        import paho.mqtt.client as mqtt  # noqa: PLC0415 — optional dep, only needed here
    except ImportError:
        return {"ok": False, "error": "python3-paho-mqtt not installed — re-run scripts/07-power-drawer.sh"}

    result: dict[str, Any] = {"ok": False, "error": "timed out"}

    def on_connect(client, userdata, flags, reason_code, properties=None):  # noqa: ANN001
        rc = int(getattr(reason_code, "value", reason_code))
        if rc == 0:
            result["ok"] = True
            result.pop("error", None)
        else:
            result["ok"] = False
            result["error"] = mqtt.connack_string(rc) if hasattr(mqtt, "connack_string") else f"rc={rc}"
        client.disconnect()

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        if user:
            client.username_pw_set(user, password)
        client.on_connect = on_connect
        client.connect(host, port, keepalive=5)
        client.loop_start()
        deadline = 6.0
        import time as _time  # noqa: PLC0415

        start = _time.time()
        while _time.time() - start < deadline and result.get("error") == "timed out":
            _time.sleep(0.1)
        client.loop_stop()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "HaKioskSetup/1.0"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, path: pathlib.Path) -> None:
        if not path.exists():
            self._json(404, {"ok": False, "error": f"missing: {path}"})
            return
        data = path.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
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
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._json(200, {"ok": True})
            return
        if path in ("/", "/setup"):
            self._html(STATIC_DIR / "setup.html")
            return
        if path == "/api/current":
            self._json(
                200,
                {
                    "ok": True,
                    "url": read_current_url(),
                    "user": read_current_user(),
                    "has_password": has_password(),
                },
            )
            return
        if path == "/api/mqtt-current":
            self._json(200, {"ok": True, **read_mqtt_config()})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        body = self._read_json()

        if path == "/api/test-url":
            url = str(body.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                self._json(400, {"ok": False, "error": "URL must start with http:// or https://"})
                return
            self._json(200, test_url(url))
            return

        if path == "/api/save-ha":
            url = str(body.get("url", "")).strip()
            user = str(body.get("user", "")).strip()
            password = str(body.get("pass", "")).strip()
            if not url.startswith(("http://", "https://")):
                self._json(400, {"ok": False, "error": "URL must start with http:// or https://"})
                return
            try:
                write_ha_config(url, user, password)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
                return
            restarted = None
            if body.get("restart", True):
                try:
                    restarted = restart_kiosk()
                except Exception as exc:  # noqa: BLE001
                    self._json(200, {"ok": True, "saved": True, "restart_error": str(exc)})
                    return
            self._json(200, {"ok": True, "saved": True, "restarted": restarted})
            return

        if path == "/api/restart-kiosk":
            try:
                restarted = restart_kiosk()
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "restarted": restarted})
            return

        if path == "/api/wifi-scan":
            try:
                self._json(200, {"ok": True, "networks": wifi_scan()})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/wifi-connect":
            ssid = str(body.get("ssid", "")).strip()
            password = str(body.get("password", "")).strip()
            if not ssid:
                self._json(400, {"ok": False, "error": "ssid required"})
                return
            try:
                self._json(200, wifi_connect(ssid, password))
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/mqtt-test":
            host = str(body.get("host", "")).strip()
            try:
                port = int(body.get("port") or 1883)
            except (TypeError, ValueError):
                self._json(400, {"ok": False, "error": "port must be a number"})
                return
            user = str(body.get("user", "")).strip()
            password = str(body.get("pass", "")).strip()
            if not password and user and read_mqtt_config()["user"] == user:
                # Unchanged password field, same user as saved — reuse the stored one.
                password = _parse_env(MQTT_ENV_FILE).get("MQTT_PASSWORD", "")
            self._json(200, test_mqtt(host, port, user, password))
            return

        if path == "/api/save-mqtt":
            host = str(body.get("host", "")).strip()
            port = str(body.get("port", "")).strip() or "1883"
            user = str(body.get("user", "")).strip()
            password = str(body.get("pass", "")).strip()
            enabled = bool(body.get("enabled", False))
            if enabled and not host:
                self._json(400, {"ok": False, "error": "Broker host required to enable"})
                return
            try:
                write_mqtt_config(host, port, user, password)
                set_mqtt_enabled(enabled)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "saved": True, "enabled": enabled})
            return

        self._json(404, {"ok": False, "error": "not found"})


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"setup wizard on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
