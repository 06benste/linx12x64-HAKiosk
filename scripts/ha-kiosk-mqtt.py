#!/usr/bin/env python3
"""
Publish Linx HA kiosk as an MQTT Discovery device in Home Assistant.

Reads /opt/ha-kiosk/mqtt.env and talks to the local power API on 127.0.0.1:17823.
"""
from __future__ import annotations

import json
import os
import pathlib
import pwd
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # pragma: no cover
    raise SystemExit("python3-paho-mqtt required") from exc

INSTALL = pathlib.Path("/opt/ha-kiosk")
ENV_FILE = INSTALL / "mqtt.env"
API = "http://127.0.0.1:17823"
DEVICE_ID = "hakiosk_tablet"
DISC_PREFIX = "homeassistant"
STATE_PREFIX = f"hakiosk/{DEVICE_ID}"
AVAIL_TOPIC = f"{STATE_PREFIX}/status"
CAMERA_STREAM_TOPIC = f"{STATE_PREFIX}/camera_stream"
CAMERA_STREAM_ATTR_TOPIC = f"{STATE_PREFIX}/camera_stream_attr"
CAMERA_POWER_TOPIC = f"{STATE_PREFIX}/camera_power"
CAMERA_POWER_FILE = INSTALL / "config" / "camera_power"
CHGLED_STATE_FILE = INSTALL / "config" / "chgled"
SCREENSHOT_TOPIC = f"{STATE_PREFIX}/screen_shot"
SCREENSHOT_ATTR_TOPIC = f"{STATE_PREFIX}/screen_shot_attr"
SCREENSHOT_JPEG = pathlib.Path("/tmp/ha-kiosk-screen.jpg")
SCREENSHOT_PNG = pathlib.Path("/tmp/ha-kiosk-screen-raw.png")
XAUTHORITY = pathlib.Path("/home/kioskuser/.Xauthority")
X11_SOCKET = pathlib.Path("/tmp/.X11-unix/X0")
try:
    _KIOSK_UID = pwd.getpwnam("kioskuser").pw_uid
except KeyError:
    _KIOSK_UID = None
KIOSK_RUNTIME_DIR = pathlib.Path(f"/run/user/{_KIOSK_UID}") if _KIOSK_UID is not None else None
STREAM_MJPEG_PATH = "/stream.mjpg"
# Removed entities — publish empty retained discovery so HA deletes them.
REMOVED_DISCOVERY = (
    ("camera", "front"),
    ("button", "camera_snapshot"),
    ("sensor", "camera_status"),
    ("sensor", "camera_stream_url"),
    # Renamed to "camera_stream" — it was never actually front-only (the
    # underlying still reflects whichever facing is currently selected,
    # front or rear), the old name just implied otherwise.
    ("camera", "front_stream"),
)


def load_env(path: pathlib.Path) -> dict[str, str]:
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


def api_get(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{API}{path}", timeout=8) as resp:
        return json.loads(resp.read().decode())


def api_post(path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def stream_api_get(path: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or {}
    port = int(env.get("CAMERA_STREAM_PORT", os.environ.get("CAMERA_STREAM_PORT", "17824")))
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=8) as resp:
        return json.loads(resp.read().decode())


def stream_api_post(path: str, body: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or {}
    port = int(env.get("CAMERA_STREAM_PORT", os.environ.get("CAMERA_STREAM_PORT", "17824")))
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


CAMERA_INPUT_FILE = INSTALL / "config" / "camera_input"


def load_camera_facing(env: dict[str, str] | None = None) -> str:
    env = env or {}
    try:
        st = stream_api_get("/api/input", env)
        facing = str(st.get("facing") or "").lower()
        if facing in ("front", "rear"):
            return facing
    except Exception:
        pass
    try:
        raw = CAMERA_INPUT_FILE.read_text(encoding="utf-8").strip().lower()
        if raw in ("1", "rear", "back"):
            return "rear"
    except Exception:
        pass
    return "front"


def load_camera_power(env: dict[str, str] | None = None) -> bool:
    """Persisted HA switch state; default ON (or CAMERA_ENABLED from env)."""
    env = env or {}
    if CAMERA_POWER_FILE.exists():
        val = CAMERA_POWER_FILE.read_text(encoding="utf-8").strip().lower()
        return val not in ("0", "off", "false", "no")
    return env.get("CAMERA_ENABLED", "1").strip() not in ("0", "false", "False", "no")


def load_chgled_on() -> bool:
    """Mirrors power-api.py's load_chgled_on() — same file, default ON."""
    if CHGLED_STATE_FILE.exists():
        val = CHGLED_STATE_FILE.read_text(encoding="utf-8").strip().lower()
        return val not in ("0", "off", "false", "no")
    return True


def device_block() -> dict[str, Any]:
    return {
        "identifiers": [DEVICE_ID],
        "name": "HA Kiosk Tablet",
        "manufacturer": "Linx",
        "model": "12X64 (Atom x5-Z8350)",
        "sw_version": "debian-kiosk",
        "configuration_url": f"http://{socket.gethostbyname(socket.gethostname())}:17823/health"
        if False
        else None,
    }


def clean_device() -> dict[str, Any]:
    d = {
        "identifiers": [DEVICE_ID],
        "name": "HA Kiosk Tablet",
        "manufacturer": "Linx",
        "model": "12X64",
        "sw_version": "debian-kiosk",
    }
    # Prefer stable LAN IP from status when publishing
    return d


def discovery_configs(ip_hint: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    device = clean_device()
    ip = ip_hint or "192.168.8.201"
    port = int(os.environ.get("CAMERA_STREAM_PORT", "17824"))
    device["configuration_url"] = f"http://{ip}:{port}{STREAM_MJPEG_PATH}"

    avail = {
        "topic": AVAIL_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
    }
    base = {
        "availability": [avail],
        "device": device,
        "enabled_by_default": True,
    }

    items: list[tuple[str, dict[str, Any]]] = []

    def add(component: str, object_id: str, payload: dict[str, Any]) -> None:
        topic = f"{DISC_PREFIX}/{component}/{DEVICE_ID}/{object_id}/config"
        full = {**base, **payload, "unique_id": f"{DEVICE_ID}_{object_id}", "object_id": f"hakiosk_{object_id}"}
        items.append((topic, full))

    # Sensors
    add("sensor", "hostname", {
        "name": "Hostname",
        "state_topic": f"{STATE_PREFIX}/hostname",
        "icon": "mdi:tablet",
        "entity_category": "diagnostic",
    })
    add("sensor", "ip", {
        "name": "IP Address",
        "state_topic": f"{STATE_PREFIX}/ip",
        "icon": "mdi:ip-network",
        "entity_category": "diagnostic",
    })
    add("sensor", "wifi_ssid", {
        "name": "Wi‑Fi SSID",
        "state_topic": f"{STATE_PREFIX}/wifi_ssid",
        "icon": "mdi:wifi",
        "entity_category": "diagnostic",
    })
    add("sensor", "wifi_signal", {
        "name": "Wi‑Fi Signal",
        "state_topic": f"{STATE_PREFIX}/wifi_signal",
        "unit_of_measurement": "%",
        "device_class": "signal_strength",
        "state_class": "measurement",
        "icon": "mdi:wifi-strength-3",
        "entity_category": "diagnostic",
    })
    add("sensor", "wifi_quality", {
        "name": "Wi‑Fi Quality",
        "state_topic": f"{STATE_PREFIX}/wifi_quality",
        "state_class": "measurement",
        "icon": "mdi:wifi-star",
        "entity_category": "diagnostic",
    })
    add("sensor", "wifi_level", {
        "name": "Wi‑Fi Level",
        "state_topic": f"{STATE_PREFIX}/wifi_level",
        "unit_of_measurement": "dBm",
        "device_class": "signal_strength",
        "state_class": "measurement",
        "icon": "mdi:wifi",
        "entity_category": "diagnostic",
    })
    add("sensor", "cpu_temperature", {
        "name": "CPU Temperature",
        "state_topic": f"{STATE_PREFIX}/cpu_temperature",
        "unit_of_measurement": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:thermometer",
    })
    add("sensor", "soc_temperature", {
        "name": "SoC Temperature",
        "state_topic": f"{STATE_PREFIX}/soc_temperature",
        "unit_of_measurement": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
        "icon": "mdi:chip",
        "entity_category": "diagnostic",
    })
    add("sensor", "disk_used_percent", {
        "name": "Disk Used",
        "state_topic": f"{STATE_PREFIX}/disk_used_percent",
        "unit_of_measurement": "%",
        "state_class": "measurement",
        "icon": "mdi:harddisk",
    })
    add("sensor", "disk_free_gb", {
        "name": "Disk Free",
        "state_topic": f"{STATE_PREFIX}/disk_free_gb",
        "unit_of_measurement": "GB",
        "state_class": "measurement",
        "icon": "mdi:harddisk",
        "entity_category": "diagnostic",
    })
    add("sensor", "uptime", {
        "name": "Uptime",
        "state_topic": f"{STATE_PREFIX}/uptime",
        "unit_of_measurement": "s",
        "device_class": "duration",
        "state_class": "total_increasing",
        "icon": "mdi:timer-outline",
        "entity_category": "diagnostic",
    })
    add("sensor", "load_1m", {
        "name": "Load 1m",
        "state_topic": f"{STATE_PREFIX}/load_1m",
        "state_class": "measurement",
        "icon": "mdi:chip",
        "entity_category": "diagnostic",
    })
    add("sensor", "memory_used", {
        "name": "Memory Used",
        "state_topic": f"{STATE_PREFIX}/memory_used",
        "unit_of_measurement": "%",
        "state_class": "measurement",
        "icon": "mdi:memory",
        "entity_category": "diagnostic",
    })
    add("sensor", "rotation", {
        "name": "Rotation",
        "state_topic": f"{STATE_PREFIX}/rotation",
        "icon": "mdi:screen-rotation",
        "entity_category": "diagnostic",
    })
    add("binary_sensor", "ha_reachable", {
        "name": "HA Reachable",
        "state_topic": f"{STATE_PREFIX}/ha_reachable",
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": "connectivity",
        "entity_category": "diagnostic",
    })
    add("sensor", "battery", {
        "name": "Battery",
        "state_topic": f"{STATE_PREFIX}/battery",
        "unit_of_measurement": "%",
        "device_class": "battery",
        "state_class": "measurement",
        "icon": "mdi:battery",
    })
    add("sensor", "battery_status", {
        "name": "Battery Status",
        "state_topic": f"{STATE_PREFIX}/battery_status",
        "icon": "mdi:battery-heart-variant",
        "entity_category": "diagnostic",
    })
    add("sensor", "battery_voltage", {
        "name": "Battery Voltage",
        "state_topic": f"{STATE_PREFIX}/battery_voltage",
        "unit_of_measurement": "V",
        "device_class": "voltage",
        "state_class": "measurement",
        "entity_category": "diagnostic",
        "icon": "mdi:flash",
    })
    add("binary_sensor", "plugged_in", {
        "name": "Plugged In",
        "state_topic": f"{STATE_PREFIX}/plugged_in",
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": "plug",
        "icon": "mdi:power-plug",
    })
    add("binary_sensor", "charging", {
        "name": "Charging",
        "state_topic": f"{STATE_PREFIX}/charging",
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": "battery_charging",
        "icon": "mdi:battery-charging",
    })
    add("binary_sensor", "charger_inadequate", {
        "name": "Charger Inadequate",
        "state_topic": f"{STATE_PREFIX}/charger_inadequate",
        "payload_on": "ON",
        "payload_off": "OFF",
        "device_class": "problem",
        "icon": "mdi:power-plug-off",
        # "Plugged In" only reflects whether AC/USB was detected at all — it
        # can (and on this tablet has) stayed ON while the battery drains
        # anyway, because the charger/cable simply can't supply what the
        # kiosk draws. This is the "online" AND "still net-discharging"
        # combination that actually predicts an eventual hard-cut, made
        # visible in HA instead of only discoverable via SSH mid-crisis.
    })

    # Brightness number (0-100)
    add("number", "brightness", {
        "name": "Brightness",
        "state_topic": f"{STATE_PREFIX}/brightness",
        "command_topic": f"{STATE_PREFIX}/cmd/brightness",
        "min": 5,
        "max": 100,
        "step": 5,
        "unit_of_measurement": "%",
        "icon": "mdi:brightness-6",
        "mode": "slider",
    })

    # Switches / buttons
    add("switch", "night_mode", {
        "name": "Night Mode",
        "state_topic": f"{STATE_PREFIX}/night_mode",
        "command_topic": f"{STATE_PREFIX}/cmd/night_mode",
        "payload_on": "ON",
        "payload_off": "OFF",
        "icon": "mdi:weather-night",
    })
    add("sensor", "screen_status", {
        "name": "Screen Status",
        "state_topic": f"{STATE_PREFIX}/screen_status",
        "icon": "mdi:monitor",
    })
    add("button", "display_blank", {
        "name": "Blank Display",
        "command_topic": f"{STATE_PREFIX}/cmd/display_blank",
        "icon": "mdi:monitor-off",
    })
    add("button", "display_wake", {
        "name": "Wake Display",
        "command_topic": f"{STATE_PREFIX}/cmd/display_wake",
        "icon": "mdi:monitor",
    })
    add("button", "refresh", {
        "name": "Refresh Dashboard",
        "command_topic": f"{STATE_PREFIX}/cmd/refresh",
        "icon": "mdi:refresh",
    })
    add("button", "restart_display", {
        "name": "Restart Display",
        "command_topic": f"{STATE_PREFIX}/cmd/restart_display",
        "icon": "mdi:monitor-screenshot",
        "entity_category": "diagnostic",
    })
    add("button", "clear_cache", {
        "name": "Clear Cache",
        "command_topic": f"{STATE_PREFIX}/cmd/clear_cache",
        "icon": "mdi:cached",
        "entity_category": "diagnostic",
    })
    add("button", "reboot", {
        "name": "Restart Tablet",
        "command_topic": f"{STATE_PREFIX}/cmd/reboot",
        "icon": "mdi:restart",
        "entity_category": "diagnostic",
        "device_class": "restart",
    })
    add("button", "shutdown", {
        "name": "Shut Down Tablet",
        "command_topic": f"{STATE_PREFIX}/cmd/shutdown",
        "icon": "mdi:power",
        "entity_category": "diagnostic",
    })

    # Rotation select
    add("select", "orientation", {
        "name": "Orientation",
        "state_topic": f"{STATE_PREFIX}/rotation",
        "command_topic": f"{STATE_PREFIX}/cmd/orientation",
        "options": ["normal", "left", "right", "inverted"],
        "icon": "mdi:phone-rotate-landscape",
    })

    # Camera master switch + live MQTT stream frames
    add("switch", "camera", {
        "name": "Camera",
        "state_topic": CAMERA_POWER_TOPIC,
        "command_topic": f"{STATE_PREFIX}/cmd/camera",
        "payload_on": "ON",
        "payload_off": "OFF",
        "icon": "mdi:webcam",
    })
    add("camera", "camera_stream", {
        "name": "Camera Stream",
        "topic": CAMERA_STREAM_TOPIC,
        "icon": "mdi:cctv",
        "encoding": "",
        "json_attributes_topic": CAMERA_STREAM_ATTR_TOPIC,
        # Frames publish with retain=False, so a powered-off camera simply
        # stops sending new ones — that alone doesn't clear whatever frame
        # HA's frontend already has cached, since the entity itself stays
        # "available" (device online) the whole time. Gating availability on
        # camera_power too (mode "all" = both must say available) is what
        # actually makes HA drop the stale image instead of showing it
        # forever once the camera turns off.
        "availability": [
            avail,
            {
                "topic": CAMERA_POWER_TOPIC,
                "payload_available": "ON",
                "payload_not_available": "OFF",
            },
        ],
        "availability_mode": "all",
    })
    add("select", "camera_facing", {
        "name": "Camera Facing",
        "state_topic": f"{STATE_PREFIX}/camera_facing",
        "command_topic": f"{STATE_PREFIX}/cmd/camera_facing",
        "options": ["front", "rear"],
        "icon": "mdi:camera-flip",
    })
    add("camera", "screen", {
        "name": "Screen",
        "topic": SCREENSHOT_TOPIC,
        "icon": "mdi:monitor-screenshot",
        "encoding": "",
        "json_attributes_topic": SCREENSHOT_ATTR_TOPIC,
    })

    # Charge LED — direct AXP288 i2c register control (see power-api.py's
    # set_chgled), not something the kernel or ACPI exposes on this board.
    add("switch", "chgled", {
        "name": "Charge LED",
        "state_topic": f"{STATE_PREFIX}/chgled",
        "command_topic": f"{STATE_PREFIX}/cmd/chgled",
        "payload_on": "ON",
        "payload_off": "OFF",
        "icon": "mdi:led-on",
    })

    return items


class Bridge:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.night = False
        # Master HA switch — stops/starts camera stream service.
        self.camera_power = load_camera_power(env)
        self.camera_facing = load_camera_facing(env)
        self.chgled_on = load_chgled_on()
        self.stream_mqtt_enabled = (
            env.get("CAMERA_STREAM_MQTT", "1").strip() not in ("0", "false", "False", "no")
        )
        # Each MQTT still fetches /snapshot.jpg, which counts as a client on
        # camera-stream-server.py's FrameBroker — that broker only stops the
        # v4l2/ffmpeg capture pipeline (and the ISP behind it) after 45s with
        # no clients. At the old 1fps default a new poll always landed well
        # inside that window, so the full capture pipeline never actually got
        # to idle — it ran flat-out 24/7 just to serve an occasional MQTT
        # thumbnail, camera viewed or not. Defaulting below 1/45Hz lets the
        # broker's own idle-stop actually engage between polls. Raise this
        # back toward 1 only if you specifically need snappier MQTT stills —
        # that's traded directly for the capture pipeline never resting.
        self.stream_mqtt_fps = max(0.005, float(env.get("CAMERA_STREAM_MQTT_FPS", "0.0167")))
        self.screenshot_enabled = (
            env.get("SCREENSHOT_ENABLED", "1").strip() not in ("0", "false", "False", "no")
        )
        self.screenshot_interval = max(5, int(env.get("SCREENSHOT_INTERVAL", "30")))
        self.screenshot_width = max(320, int(env.get("SCREENSHOT_WIDTH", "960")))
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"hakiosk-{socket.gethostname()}",
            protocol=mqtt.MQTTv311,
        )
        user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
        password = env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or ""
        if user:
            self.client.username_pw_set(user, password)
        self.client.will_set(AVAIL_TOPIC, "offline", qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        rc = int(getattr(reason_code, "value", reason_code))
        print(f"mqtt connected rc={rc}", flush=True)
        if rc != 0:
            return
        client.subscribe(f"{STATE_PREFIX}/cmd/#", qos=1)
        self.publish_discovery()
        client.publish(AVAIL_TOPIC, "online", qos=1, retain=True)
        self.clear_removed_discovery()
        # Apply persisted camera power (start or stop stream service).
        self.apply_camera_power(self.camera_power, reason="startup")
        self.publish_state()
        if self.stream_mqtt_enabled:
            self._ensure_stream_publisher()
        if self.screenshot_enabled:
            self._ensure_screenshot_publisher()
        self._ensure_local_state_watcher()

    def on_message(self, client, userdata, msg) -> None:
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        try:
            self.handle_command(topic, payload)
        except Exception as exc:  # noqa: BLE001
            print(f"cmd error {topic}: {exc}", flush=True)
        try:
            self.publish_state()
        except Exception:
            pass

    def handle_command(self, topic: str, payload: str) -> None:
        cmd = topic.rsplit("/", 1)[-1]
        if cmd == "brightness":
            api_post("/brightness", {"percent": int(float(payload))})
            self.night = False
        elif cmd == "night_mode":
            if payload.upper() == "ON":
                api_post("/night-on")
                self.night = True
            else:
                api_post("/night-off")
                self.night = False
        elif cmd == "display_blank":
            api_post("/display-off")
            self._publish_screen_status("blanked")
        elif cmd == "display_wake":
            api_post("/display-on")
            self._publish_screen_status("on")
        elif cmd == "refresh":
            api_post("/refresh")
        elif cmd == "restart_display":
            api_post("/chromium-restart")
            self._publish_screen_status("on")
        elif cmd == "clear_cache":
            api_post("/clear-cache")
            self._publish_screen_status("on")
        elif cmd == "reboot":
            api_post("/reboot")
        elif cmd == "shutdown":
            api_post("/shutdown")
        elif cmd == "orientation":
            api_post("/rotate", {"direction": payload})
        elif cmd == "camera":
            self.apply_camera_power(payload.upper() in ("ON", "1", "TRUE"), reason="switch")
        elif cmd == "camera_facing":
            facing = payload.strip().lower()
            if facing not in ("front", "rear"):
                raise RuntimeError(f"bad camera_facing {payload!r}")
            stream_api_post("/api/input", {"facing": facing}, self.env)
            self.camera_facing = facing
            self.client.publish(
                f"{STATE_PREFIX}/camera_facing",
                facing,
                qos=1,
                retain=True,
            )
        elif cmd == "chgled":
            want = payload.upper() in ("ON", "1", "TRUE")
            result = api_post("/chgled", {"on": want})
            self.chgled_on = bool(result.get("on", want))
            self.client.publish(
                f"{STATE_PREFIX}/chgled",
                "ON" if self.chgled_on else "OFF",
                qos=1,
                retain=True,
            )
        else:
            print(f"unknown cmd {cmd}", flush=True)

    def apply_camera_power(self, on: bool, reason: str = "") -> None:
        """Delegate the actual start/stop to power-api's /camera, which is the
        single place that owns the systemd unit — so the drawer's Camera
        toggle and this MQTT switch can never disagree about whether the
        stream service should be running."""
        want = bool(on)
        print(f"camera power {'ON' if want else 'OFF'} ({reason})", flush=True)
        try:
            result = api_post("/camera", {"on": want})
            self.camera_power = bool(result.get("on", want))
        except Exception as exc:  # noqa: BLE001
            print(f"camera power toggle via power-api failed: {exc}", flush=True)
            self.camera_power = load_camera_power(self.env)
        if self.camera_power:
            self._ensure_stream_publisher()
        try:
            self.client.publish(
                CAMERA_POWER_TOPIC,
                "ON" if self.camera_power else "OFF",
                qos=1,
                retain=True,
            )
        except Exception:
            pass

    def _tablet_ip(self) -> str:
        try:
            st = api_get("/status")
            ip = (st.get("wifi") or {}).get("ip")
            if ip:
                return str(ip)
        except Exception:
            pass
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "192.168.8.201"

    def publish_stream_attrs(self) -> None:
        ip = self._tablet_ip()
        port = int(self.env.get("CAMERA_STREAM_PORT", os.environ.get("CAMERA_STREAM_PORT", "17824")))
        stream_fps = float(self.env.get("CAMERA_STREAM_FPS", os.environ.get("CAMERA_STREAM_FPS", "15")))
        if self.camera_power:
            mjpeg = f"http://{ip}:{port}{STREAM_MJPEG_PATH}"
            snap = f"http://{ip}:{port}/snapshot.jpg"
        else:
            mjpeg = ""
            snap = ""
        self.client.publish(
            CAMERA_STREAM_ATTR_TOPIC,
            json.dumps(
                {
                    "mjpeg_url": mjpeg,
                    "snapshot_url": snap,
                    "live_url": mjpeg,
                    "facing": getattr(self, "camera_facing", "front"),
                    "stream_fps": stream_fps if self.camera_power else 0,
                    "mqtt_still_fps": self.stream_mqtt_fps if self.camera_power else 0,
                    "camera_power": "ON" if self.camera_power else "OFF",
                    "note": (
                        "Live video: point an HA mjpeg camera at live_url. "
                        "This MQTT entity is stills only."
                    ),
                }
            ),
            qos=0,
            retain=True,
        )

    def publish_stream_frame(self, jpeg: bytes) -> None:
        self.client.publish(CAMERA_STREAM_TOPIC, jpeg, qos=0, retain=False)

    def _stream_publisher_loop(self) -> None:
        period = 1.0 / self.stream_mqtt_fps
        port = int(self.env.get("CAMERA_STREAM_PORT", os.environ.get("CAMERA_STREAM_PORT", "17824")))
        # Prefer discrete snapshots over a long-lived MJPEG socket — avoids
        # leaking stream clients when AtomISP stalls mid-connection.
        url = f"http://127.0.0.1:{port}/snapshot.jpg"
        print(f"stream mqtt publisher started @ {self.stream_mqtt_fps} fps via {url}", flush=True)
        time.sleep(3.0)
        while True:
            if not self.camera_power:
                time.sleep(1.0)
                continue
            t0 = time.time()
            try:
                with urllib.request.urlopen(url, timeout=20) as resp:
                    jpeg = resp.read()
                if jpeg and len(jpeg) >= 800:
                    self.publish_stream_frame(jpeg)
            except Exception as exc:  # noqa: BLE001
                if self.camera_power:
                    print(f"stream mqtt snapshot: {exc}", flush=True)
                time.sleep(2.0)
                continue
            elapsed = time.time() - t0
            time.sleep(max(0.05, period - elapsed))

    def _ensure_stream_publisher(self) -> None:
        if getattr(self, "_stream_thread", None) and self._stream_thread.is_alive():  # type: ignore[attr-defined]
            return
        import threading

        self._stream_thread = threading.Thread(target=self._stream_publisher_loop, daemon=True)
        self._stream_thread.start()

    def _local_state_watcher_loop(self) -> None:
        """camera_power and chgled can each be changed two ways: this MQTT
        switch, or the on-tablet drawer talking straight to power-api. The
        drawer path writes the same on-disk file power-api owns but doesn't
        tell this bridge about it, so without this loop the MQTT state would
        lag up to MQTT_INTERVAL (default 30s) behind whatever the drawer
        just did. These two files are tiny and local — polling them every
        couple seconds is far cheaper than shortening the whole
        publish_state() cycle (wifi/thermal/disk/etc.) just to close this
        one gap."""
        while True:
            time.sleep(2.0)
            try:
                chgled_on = load_chgled_on()
                if chgled_on != self.chgled_on:
                    self.chgled_on = chgled_on
                    self.client.publish(
                        f"{STATE_PREFIX}/chgled",
                        "ON" if chgled_on else "OFF",
                        qos=1,
                        retain=True,
                    )
            except Exception:
                pass
            try:
                camera_power = load_camera_power(self.env)
                if camera_power != self.camera_power:
                    self.camera_power = camera_power
                    self.client.publish(
                        CAMERA_POWER_TOPIC,
                        "ON" if camera_power else "OFF",
                        qos=1,
                        retain=True,
                    )
            except Exception:
                pass

    def _ensure_local_state_watcher(self) -> None:
        if getattr(self, "_local_state_thread", None) and self._local_state_thread.is_alive():  # type: ignore[attr-defined]
            return
        import threading

        self._local_state_thread = threading.Thread(target=self._local_state_watcher_loop, daemon=True)
        self._local_state_thread.start()

    def _find_wayland_socket(self) -> pathlib.Path | None:
        if KIOSK_RUNTIME_DIR is None or not KIOSK_RUNTIME_DIR.exists():
            return None
        for entry in sorted(KIOSK_RUNTIME_DIR.glob("wayland-*")):
            try:
                if stat.S_ISSOCK(entry.stat().st_mode):
                    return entry
            except OSError:
                continue
        return None

    def _capture_via_grim(self) -> bytes:
        """cage is wlroots-based and (on recent versions) speaks the
        wlr-screencopy protocol grim needs — untested on this specific cage
        build, hence the graceful fallback in capture_screenshot_jpeg rather
        than replacing the X11 path outright. This service is a separate
        systemd unit, not a child of cage, so it doesn't inherit
        WAYLAND_DISPLAY/XDG_RUNTIME_DIR automatically — found and set
        explicitly instead."""
        sock = self._find_wayland_socket()
        if sock is None:
            raise RuntimeError("no Wayland compositor socket found under " + str(KIOSK_RUNTIME_DIR))
        env = os.environ.copy()
        env["XDG_RUNTIME_DIR"] = str(KIOSK_RUNTIME_DIR)
        env["WAYLAND_DISPLAY"] = sock.name
        SCREENSHOT_PNG.unlink(missing_ok=True)
        proc = subprocess.run(
            ["grim", str(SCREENSHOT_PNG)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        if proc.returncode != 0 or not SCREENSHOT_PNG.exists():
            err = (proc.stderr or proc.stdout or "").strip()[-300:]
            raise RuntimeError(f"grim rc={proc.returncode}: {err or 'no file'}")
        vf = f"scale={self.screenshot_width}:-2"
        SCREENSHOT_JPEG.unlink(missing_ok=True)
        conv = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(SCREENSHOT_PNG),
                "-vf", vf, "-q:v", "6",
                str(SCREENSHOT_JPEG),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if conv.returncode != 0 or not SCREENSHOT_JPEG.exists():
            err = (conv.stderr or conv.stdout or "").strip()[-300:]
            raise RuntimeError(f"grim->jpeg convert rc={conv.returncode}: {err or 'no file'}")
        return SCREENSHOT_JPEG.read_bytes()

    def _capture_via_x11grab(self) -> bytes:
        if not X11_SOCKET.exists():
            # Only the X11 fallback kiosk (05-x11-kiosk.sh) actually has
            # /tmp/.X11-unix/X0 to grab from. Fail fast on a cheap stat()
            # instead of spawning ffmpeg (which would just error out anyway)
            # every SCREENSHOT_INTERVAL forever.
            raise RuntimeError("no X server on :0")
        env = os.environ.copy()
        env["DISPLAY"] = ":0"
        if XAUTHORITY.exists():
            env["XAUTHORITY"] = str(XAUTHORITY)
        SCREENSHOT_JPEG.unlink(missing_ok=True)
        vf = f"scale={self.screenshot_width}:-2"
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "x11grab",
                "-i",
                ":0.0",
                "-frames:v",
                "1",
                "-vf",
                vf,
                "-q:v",
                "6",
                "-update",
                "1",
                str(SCREENSHOT_JPEG),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        if proc.returncode != 0 or not SCREENSHOT_JPEG.exists():
            err = (proc.stderr or proc.stdout or "").strip()[-300:]
            raise RuntimeError(f"screenshot rc={proc.returncode}: {err or 'no file'}")
        return SCREENSHOT_JPEG.read_bytes()

    def capture_screenshot_jpeg(self) -> bytes:
        errors = []
        for method, capture in (("grim", self._capture_via_grim), ("x11grab", self._capture_via_x11grab)):
            try:
                data = capture()
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                errors.append(f"{method}: {exc}")
                continue
            if len(data) < 500 or data[:2] != b"\xff\xd8":
                errors.append(f"{method}: bad screenshot ({len(data)} bytes)")
                continue
            return data
        raise RuntimeError("; ".join(errors))

    def publish_screenshot(self, reason: str = "timer") -> None:
        try:
            jpeg = self.capture_screenshot_jpeg()
            self.client.publish(SCREENSHOT_TOPIC, jpeg, qos=0, retain=True)
            self.client.publish(
                SCREENSHOT_ATTR_TOPIC,
                json.dumps(
                    {
                        "bytes": len(jpeg),
                        "width": self.screenshot_width,
                        "interval_s": self.screenshot_interval,
                        "reason": reason,
                        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                ),
                qos=0,
                retain=True,
            )
            print(f"screenshot published {len(jpeg)} bytes ({reason})", flush=True)
            self._screenshot_error_logged = None
        except Exception as exc:  # noqa: BLE001
            # A persistent, unchanging failure (e.g. no X server under the
            # default cage/Wayland kiosk) would otherwise log identically
            # every SCREENSHOT_INTERVAL forever — only print when it's new.
            msg = str(exc)
            if msg != getattr(self, "_screenshot_error_logged", None):
                print(f"screenshot failed: {msg}", flush=True)
                self._screenshot_error_logged = msg

    def _screenshot_publisher_loop(self) -> None:
        print(
            f"screenshot publisher started every {self.screenshot_interval}s "
            f"width={self.screenshot_width}",
            flush=True,
        )
        time.sleep(2.0)
        while True:
            self.publish_screenshot(reason="timer")
            time.sleep(self.screenshot_interval)

    def _ensure_screenshot_publisher(self) -> None:
        if getattr(self, "_screenshot_thread", None) and self._screenshot_thread.is_alive():  # type: ignore[attr-defined]
            return
        import threading

        self._screenshot_thread = threading.Thread(
            target=self._screenshot_publisher_loop,
            daemon=True,
        )
        self._screenshot_thread.start()

    def clear_removed_discovery(self) -> None:
        for component, object_id in REMOVED_DISCOVERY:
            topic = f"{DISC_PREFIX}/{component}/{DEVICE_ID}/{object_id}/config"
            self.client.publish(topic, "", qos=1, retain=True)
        # Clear retained payloads that only fed the removed entities.
        for suffix in ("camera", "camera_status", "camera_stream_url"):
            self.client.publish(f"{STATE_PREFIX}/{suffix}", b"", qos=0, retain=True)

    def publish_discovery(self) -> None:
        ip = None
        try:
            st = api_get("/status")
            ip = (st.get("wifi") or {}).get("ip")
        except Exception:
            pass
        for topic, payload in discovery_configs(ip):
            self.client.publish(topic, json.dumps(payload), qos=1, retain=True)

    def publish_state(self) -> None:
        st = api_get("/status")
        wifi = st.get("wifi") or {}
        up = st.get("uptime") or {}
        mem = up.get("memory") or {}
        load = up.get("load") or [None, None, None]
        bright = st.get("brightness") or {}
        ha = st.get("ha") or {}
        power = st.get("power") or {}
        thermal = st.get("thermal") or {}
        disk = st.get("disk") or {}
        chgled = st.get("chgled") or {}

        def pub(suffix: str, value: Any) -> None:
            if value is None:
                value = ""
            self.client.publish(f"{STATE_PREFIX}/{suffix}", str(value), qos=0, retain=True)

        pub("hostname", st.get("hostname"))
        pub("ip", wifi.get("ip"))
        pub("wifi_ssid", wifi.get("ssid") or "")
        pub("wifi_signal", wifi.get("signal") if wifi.get("signal") is not None else "")
        pub("wifi_quality", wifi.get("quality") if wifi.get("quality") is not None else "")
        pub("wifi_level", wifi.get("level_dbm") if wifi.get("level_dbm") is not None else "")
        pub("uptime", int(up.get("seconds") or 0))
        pub("load_1m", load[0] if load else "")
        pub("memory_used", mem.get("used_pct") if mem.get("used_pct") is not None else "")
        pub("rotation", st.get("rotation") or "normal")
        pub("ha_reachable", "ON" if ha.get("ok") else "OFF")
        pub("brightness", bright.get("percent") if bright.get("percent") is not None else "")
        pub("night_mode", "ON" if self.night else "OFF")
        pub("battery", power.get("battery_percent") if power.get("battery_percent") is not None else "")
        pub("battery_status", power.get("battery_status") or "")
        pub("battery_voltage", power.get("voltage_v") if power.get("voltage_v") is not None else "")
        pub("plugged_in", "ON" if power.get("plugged_in") else "OFF")
        pub("charging", "ON" if power.get("charging") else "OFF")
        charger_inadequate = bool(power.get("plugged_in")) and str(power.get("battery_status") or "").lower() == "discharging"
        pub("charger_inadequate", "ON" if charger_inadequate else "OFF")
        # power-api.py is the single source of truth (it's the one that
        # actually writes the AXP288 register) — read its state back here
        # each cycle rather than a separate local file read, same round
        # trip this function already made for power/thermal/etc.
        self.chgled_on = chgled.get("on") if "on" in chgled else self.chgled_on
        pub("chgled", "ON" if self.chgled_on else "OFF")
        pub("cpu_temperature", thermal.get("cpu_c") if thermal.get("cpu_c") is not None else "")
        pub("soc_temperature", thermal.get("soc_c") if thermal.get("soc_c") is not None else "")
        pub("disk_used_percent", disk.get("used_percent") if disk.get("used_percent") is not None else "")
        try:
            facing = load_camera_facing(self.env)
            self.camera_facing = facing
        except Exception:
            facing = getattr(self, "camera_facing", "front")
        pub("camera_facing", facing)
        pub("disk_free_gb", disk.get("free_gb") if disk.get("free_gb") is not None else "")
        # Re-read from disk so a toggle made via the on-tablet drawer (which
        # writes the same file through power-api's /camera, not through us)
        # shows up here too, not just changes made via this MQTT switch.
        try:
            self.camera_power = load_camera_power(self.env)
        except Exception:
            pass
        pub("camera_power", "ON" if self.camera_power else "OFF")
        display = st.get("display") or {}
        screen_state = display.get("state") or ("blanked" if display.get("blanked") else "on")
        if screen_state not in ("on", "blanked"):
            screen_state = "unknown"
        pub("screen_status", screen_state)
        self.publish_stream_attrs()
        self.client.publish(AVAIL_TOPIC, "online", qos=1, retain=True)

    def _publish_screen_status(self, state: str) -> None:
        try:
            self.client.publish(f"{STATE_PREFIX}/screen_status", state, qos=0, retain=True)
        except Exception:
            pass

    def run(self) -> None:
        host = self.env.get("MQTT_HOST", "192.168.8.110")
        port = int(self.env.get("MQTT_PORT", "1883"))
        print(f"connecting mqtt://{host}:{port}", flush=True)
        print(
            f"camera power={'ON' if self.camera_power else 'OFF'} "
            f"stream_mqtt={self.stream_mqtt_enabled}@{self.stream_mqtt_fps}fps "
            f"screenshot={self.screenshot_enabled}@{self.screenshot_interval}s",
            flush=True,
        )
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()
        interval = int(self.env.get("MQTT_INTERVAL", "30"))
        while True:
            try:
                self.publish_state()
            except Exception as exc:  # noqa: BLE001
                print(f"state publish failed: {exc}", flush=True)
            time.sleep(interval)


def main() -> None:
    env = load_env(ENV_FILE)
    env.update({k: v for k, v in os.environ.items() if k.startswith("MQTT_")})
    if not env.get("MQTT_HOST"):
        env["MQTT_HOST"] = "192.168.8.110"
    if not (env.get("MQTT_USER") or env.get("MQTT_USERNAME")):
        print(f"Waiting for MQTT credentials in {ENV_FILE}", flush=True)
        print("Need MQTT_USER=... and MQTT_PASSWORD=...", flush=True)
        while True:
            time.sleep(10)
            env = load_env(ENV_FILE)
            env.update({k: v for k, v in os.environ.items() if k.startswith("MQTT_")})
            if env.get("MQTT_USER") or env.get("MQTT_USERNAME"):
                break
            print("still waiting for mqtt.env ...", flush=True)
    Bridge(env).run()


if __name__ == "__main__":
    main()
