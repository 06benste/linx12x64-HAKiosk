#!/usr/bin/env bash
# Replace broken Wayland/cage kiosk with X11 + Chromium (Linx / Cherry Trail).
# Fixes: "Found 0 GPUs" / "Failed to open any DRM device"
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: su -   then: bash $0" >&2
  exit 1
fi

KIOSK_USER="${KIOSK_USER:-kioskuser}"
INSTALL_ROOT="/opt/ha-kiosk"
HOME_DIR="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"

if [[ -z "$HOME_DIR" ]]; then
  echo "User $KIOSK_USER not found" >&2
  exit 1
fi

echo "== Current graphics state =="
echo "cmdline: $(cat /proc/cmdline)"
ls -l /dev/dri 2>/dev/null || echo "No /dev/dri (no DRM — cage cannot work)"
lsmod | grep -E 'i915|drm' || echo "No i915/drm modules loaded"
echo

# Drop nomodeset (blocks DRM). Keep Cherry Trail stabilizers.
if [[ -f /etc/default/grub ]]; then
  cp -a /etc/default/grub /etc/default/grub.bak-x11 || true
  # remove nomodeset
  sed -i -E 's/ *nomodeset//g' /etc/default/grub
  # ensure stabilizers present (without nomodeset)
  if ! grep -q 'intel_idle.max_cstate=' /etc/default/grub; then
    sed -i -E 's/^(GRUB_CMDLINE_LINUX_DEFAULT=")(.*)"/\1\2 intel_idle.max_cstate=0 i915.enable_psr=0 i915.enable_fbc=0 i915.enable_dc=0 idle=nomwait"/' /etc/default/grub
  fi
  update-grub
  echo "Updated GRUB (nomodeset removed if it was present)."
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  xserver-xorg \
  xserver-xorg-input-all \
  xserver-xorg-video-all \
  xinit \
  x11-xserver-utils \
  unclutter \
  openbox \
  xdotool \
  chromium \
  fonts-liberation \
  seatd \
  sudo

usermod -aG video,input,render "$KIOSK_USER" 2>/dev/null || usermod -aG video,input "$KIOSK_USER"

# X11 kiosk launcher
cat >"$INSTALL_ROOT/scripts/kiosk-x11.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
INSTALL_ROOT="/opt/ha-kiosk"
URL="$(cat "$INSTALL_ROOT/url" 2>/dev/null || true)"
SETUP_FALLBACK=0
if [[ -z "$URL" ]]; then
  # No HA URL configured yet — show the on-tablet setup wizard instead.
  URL="http://127.0.0.1:17825/setup"
  SETUP_FALLBACK=1
fi

PROFILE_DIR="$INSTALL_ROOT/chromium-profile"
EXT_DIR="$INSTALL_ROOT/chromium-extension"
mkdir -p "$PROFILE_DIR"

# Let Wi-Fi / DHCP settle after boot, then wait briefly for the target to come up.
sleep 5
if [[ "$SETUP_FALLBACK" -eq 1 ]]; then
  # Local service — just wait for it to bind its port (no long remote wait needed).
  for _ in $(seq 1 20); do
    (exec 3<>/dev/tcp/127.0.0.1/17825) 2>/dev/null && break
    sleep 0.5
  done
else
  python3 - "$URL" <<'PY' || true
import sys, time, urllib.request
url = sys.argv[1]
deadline = time.time() + 45
while time.time() < deadline:
    try:
        urllib.request.urlopen(url, timeout=2)
        break
    except Exception:
        time.sleep(1)
PY
fi

# Call Chromium binary directly — Debian wrapper injects GPU flags that hurt Z8350
CHROME="/usr/lib/chromium/chromium"
[[ -x "$CHROME" ]] || CHROME="$(command -v chromium || command -v chromium-browser)"
EXTRA=()
if [[ -f "$EXT_DIR/manifest.json" && -f "$EXT_DIR/config.js" ]]; then
  EXTRA+=(--disable-extensions-except="$EXT_DIR" --load-extension="$EXT_DIR")
else
  EXTRA+=(--disable-extensions)
fi

# Hide cursor after idle
command -v unclutter >/dev/null && unclutter -idle 0.5 -root &

# Software rendering — avoids Cherry Trail GPU hangs
exec "$CHROME" \
  --user-data-dir="$PROFILE_DIR" \
  --ozone-platform=x11 \
  --kiosk \
  --start-fullscreen \
  --start-maximized \
  --window-size=1920,1080 \
  --window-position=0,0 \
  --force-device-scale-factor=1 \
  --no-first-run \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-translate \
  --disable-features=TranslateUI,AudioServiceOutOfProcess,UseChromeOSDirectVideoDecoder \
  --disable-sync \
  --check-for-update-interval=31536000 \
  --password-store=basic \
  --autoplay-policy=no-user-gesture-required \
  --disk-cache-size=33554432 \
  --disable-pinch \
  --disable-gpu \
  --disable-gpu-compositing \
  --disable-gpu-rasterization \
  --disable-accelerated-2d-canvas \
  --disable-accelerated-video-decode \
  --disable-software-rasterizer \
  --use-gl=swiftshader \
  --disable-dev-shm-usage \
  "${EXTRA[@]}" \
  "$URL"
EOF
chmod 755 "$INSTALL_ROOT/scripts/kiosk-x11.sh"
chown -R "$KIOSK_USER:$KIOSK_USER" "$INSTALL_ROOT"

# xinitrc for the kiosk user
cat >"$HOME_DIR/.xinitrc" <<'EOF'
#!/bin/sh
# Keep-awake respects /opt/ha-kiosk/config/display_blanked (intentional blank).
rm -f /opt/ha-kiosk/config/display_blanked
/opt/ha-kiosk/scripts/keep-awake-x11.sh &
# Minimal WM so Chromium can truly fullscreen (bare X leaves a half-width window)
command -v openbox >/dev/null && openbox &
sleep 0.5
exec /opt/ha-kiosk/scripts/kiosk-x11.sh
EOF
chmod 755 "$HOME_DIR/.xinitrc"
chown "$KIOSK_USER:$KIOSK_USER" "$HOME_DIR/.xinitrc"

# Autologin tty1 → startx
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat >/etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${KIOSK_USER} --noclear %I \$TERM
EOF

cat >"$HOME_DIR/.bash_profile" <<'EOF'
# Start X11 HA kiosk on tty1
if [ "$(tty 2>/dev/null)" = "/dev/tty1" ]; then
  exec startx
fi
EOF
chown "$KIOSK_USER:$KIOSK_USER" "$HOME_DIR/.bash_profile"

# Allow kioskuser to run startx on vt1
mkdir -p /etc/X11
if [[ -f /etc/X11/Xwrapper.config ]]; then
  sed -i 's/^allowed_users=.*/allowed_users=anybody/' /etc/X11/Xwrapper.config || true
  grep -q '^allowed_users=' /etc/X11/Xwrapper.config || echo 'allowed_users=anybody' >>/etc/X11/Xwrapper.config
  grep -q '^needs_root_rights=' /etc/X11/Xwrapper.config || echo 'needs_root_rights=yes' >>/etc/X11/Xwrapper.config
else
  cat >/etc/X11/Xwrapper.config <<'EOF'
allowed_users=anybody
needs_root_rights=yes
EOF
fi

systemctl disable ha-kiosk.service 2>/dev/null || true
systemctl stop ha-kiosk.service 2>/dev/null || true
systemctl set-default multi-user.target
systemctl daemon-reload

echo
echo "X11 kiosk configured."
echo "Reboot required (especially if nomodeset was removed):"
echo "  reboot"
echo
echo "After reboot: dashboard on tty1. Text console: Ctrl+Alt+F2"
echo
echo "If it still fails after reboot, run and send output:"
echo "  ls -l /dev/dri; cat /proc/cmdline; journalctl -b | tail -n 40"
