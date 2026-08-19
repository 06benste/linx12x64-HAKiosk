#!/usr/bin/env bash
# Post-install smoke test: confirms every local service is actually up and
# responding, instead of that only ever being verified by hand (curl-ing
# six different endpoints one at a time, as this project's own maintenance
# history — a long trail of one-off _check_*/_probe_*/_diag_* scripts —
# demonstrates was otherwise the norm). Safe to re-run any time; read-only,
# touches nothing.
set -uo pipefail

PASS=0
FAIL=0
WARN=0

ok()   { printf '  [PASS] %s\n' "$1"; PASS=$((PASS + 1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL + 1)); }
warn() { printf '  [WARN] %s\n' "$1"; WARN=$((WARN + 1)); }

check_service() {
  local unit="$1" required="${2:-1}"
  if systemctl is-active --quiet "$unit"; then
    ok "$unit is active"
  elif [[ "$required" == "0" ]]; then
    warn "$unit is not active (ok if not configured/enabled yet: $unit)"
  else
    bad "$unit is not active — journalctl -u $unit"
  fi
}

check_http() {
  local name="$1" url="$2"
  local code
  code="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo 000)"
  if [[ "$code" == "200" ]]; then
    ok "$name ($url) -> 200"
  else
    bad "$name ($url) -> $code"
  fi
}

echo "=== services ==="
check_service ha-kiosk-power.service
check_service ha-kiosk-setup.service
check_service ha-kiosk-wake-on-touch.service
check_service ha-kiosk-battery-guard.service
check_service ha-kiosk-guardian.service
check_service ha-kiosk-charger-limit.service
check_service ha-kiosk-auto-rotate.service 0    # off by default until enabled from Setup > General
check_service ha-kiosk-mqtt.service 0       # off until MQTT is configured — not a failure on its own
check_service ha-kiosk-camera-stream.service 0  # off if SKIP_CAMERA=1 or camera not installed
check_service ha-kiosk-atomisp.service 0

echo
echo "=== local HTTP endpoints ==="
check_http "power-api"    "http://127.0.0.1:17823/health"
check_http "setup-wizard" "http://127.0.0.1:17825/health"
if systemctl is-active --quiet ha-kiosk-camera-stream.service; then
  check_http "camera-stream" "http://127.0.0.1:17824/health"
else
  warn "camera-stream health check skipped (service not active)"
fi

echo
echo "=== config sanity ==="
[[ -f /opt/ha-kiosk/api.token ]] && ok "api.token present" || warn "api.token missing (LAN callers to power-api/camera-stream get no auth enforcement)"
[[ -f /opt/ha-kiosk/url ]] && ok "HA URL configured ($(cat /opt/ha-kiosk/url))" || warn "no HA URL set — kiosk will show the setup wizard"
[[ -f /opt/ha-kiosk/mqtt.env ]] && ok "mqtt.env present" || warn "mqtt.env missing"
if [[ -c /dev/video0 ]]; then
  ok "/dev/video0 present"
else
  warn "/dev/video0 missing (camera not installed, or SKIP_CAMERA was used)"
fi
if command -v i2cget >/dev/null && i2cget -y -f 6 0x34 0x32 >/dev/null 2>&1; then
  ok "charge-LED control reachable (AXP288 REG32H readable over i2c)"
else
  bad "charge-LED control NOT reachable — i2c-tools missing, i2c-dev not loaded, or bus/address differs on this board"
fi
if grep -q '^RebootWatchdogSec=' /etc/systemd/system.conf 2>/dev/null; then
  ok "shutdown watchdog bounded ($(grep '^RebootWatchdogSec=' /etc/systemd/system.conf))"
else
  warn "RebootWatchdogSec not set — a wedged shutdown (e.g. AtomISP D-state) could hang up to the hardware default (often 10min) instead of a bounded reset"
fi
[[ -f /opt/ha-kiosk/version ]] && ok "version marker present ($(cat /opt/ha-kiosk/version))" || warn "no version marker — self-update's 'current version' will show as unknown until one update has been applied"
command -v curl >/dev/null && ok "curl present (needed for self-update)" || bad "curl missing — Setup > Updates tab can't check/apply updates"

echo
echo "=== chromium kiosk ==="
if pgrep -f "chromium.*--kiosk" >/dev/null; then
  ok "chromium kiosk process running"
else
  bad "no chromium kiosk process found — check: systemctl status getty@tty1.service"
fi

echo
echo "=== summary ==="
echo "  pass=$PASS warn=$WARN fail=$FAIL"
if [[ "$FAIL" -gt 0 ]]; then
  echo "  Something needs attention — see [FAIL] lines above."
  exit 1
fi
echo "  Looks healthy."
