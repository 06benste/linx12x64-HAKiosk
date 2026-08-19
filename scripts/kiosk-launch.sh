#!/usr/bin/env bash
# Launched inside cage — fullscreen Chromium to Home Assistant.
set -euo pipefail

INSTALL_ROOT="/opt/ha-kiosk"
URL_FILE="${INSTALL_ROOT}/url"
URL="$(cat "$URL_FILE" 2>/dev/null || true)"
if [[ -z "${URL}" ]]; then
  # No HA URL configured yet — show the on-tablet setup wizard instead.
  URL="http://127.0.0.1:17825/setup"
  # Give ha-kiosk-setup.service a moment to finish binding its port (no curl
  # in the minimal install — use bash's /dev/tcp instead).
  for _ in $(seq 1 20); do
    (exec 3<>/dev/tcp/127.0.0.1/17825) 2>/dev/null && break
    sleep 0.5
  done
fi

PROFILE_DIR="${INSTALL_ROOT}/chromium-profile"
EXT_DIR="${INSTALL_ROOT}/chromium-extension"

CHROME="$(command -v chromium || command -v chromium-browser || true)"
if [[ -z "$CHROME" ]]; then
  echo "chromium not found" >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"

EXTRA_ARGS=()
if [[ -f "${EXT_DIR}/manifest.json" && -f "${EXT_DIR}/config.js" ]]; then
  # Autofill HA login (credentials baked into config.js at install)
  EXTRA_ARGS+=(--disable-extensions-except="${EXT_DIR}")
  EXTRA_ARGS+=(--load-extension="${EXT_DIR}")
else
  EXTRA_ARGS+=(--disable-extensions)
fi

# Light flags for Atom Z8350 + 4GB RAM — software rendering avoids i915 GPU hangs
exec "$CHROME" \
  --user-data-dir="$PROFILE_DIR" \
  --kiosk \
  --start-fullscreen \
  --no-first-run \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-translate \
  --disable-features=TranslateUI,AudioServiceOutOfProcess,UseChromeOSDirectVideoDecoder \
  --disable-sync \
  --disable-component-update \
  --disable-background-networking \
  --disable-background-timer-throttling \
  --disable-renderer-backgrounding \
  --disable-backgrounding-occluded-windows \
  --check-for-update-interval=31536000 \
  --password-store=basic \
  --autoplay-policy=no-user-gesture-required \
  --disk-cache-size=67108864 \
  --overscroll-history-navigation=0 \
  --disable-pinch \
  --force-device-scale-factor=1 \
  --ozone-platform=wayland \
  --enable-features=UseOzonePlatform \
  --disable-gpu \
  --disable-gpu-compositing \
  --disable-gpu-rasterization \
  --disable-accelerated-2d-canvas \
  --disable-accelerated-video-decode \
  --use-gl=swiftshader \
  "${EXTRA_ARGS[@]}" \
  "$URL"
