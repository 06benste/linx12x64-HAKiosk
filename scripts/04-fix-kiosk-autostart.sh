#!/usr/bin/env bash
# Fix HA kiosk not starting (boots to text shell instead of dashboard).
#
# NOTE: 02-install-kiosk.sh applies this same tty1-direct-launch fix by
# default now (a tty7/graphical.target systemd service used to be the
# default, but nothing switches the active VT to tty7, so it silently left
# the screen on tty1's login shell). This script is now mainly for repairing
# an install that predates that change, or one that's drifted out of this
# state for some other reason. Safe to (re-)run either way — idempotent.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: su - then bash $0" >&2
  exit 1
fi

KIOSK_USER="${KIOSK_USER:-kioskuser}"
INSTALL_ROOT="/opt/ha-kiosk"
UID_NUM="$(id -u "$KIOSK_USER" 2>/dev/null || true)"

if [[ -z "$UID_NUM" ]]; then
  echo "User '$KIOSK_USER' not found. Create it or run: KIOSK_USER=youruser bash $0" >&2
  exit 1
fi

echo "== Diagnostics =="
systemctl get-default || true
systemctl is-enabled ha-kiosk.service 2>/dev/null || echo "ha-kiosk: not enabled"
systemctl status ha-kiosk.service --no-pager -l 2>/dev/null || true
echo "cmdline: $(cat /proc/cmdline)"
command -v cage || echo "MISSING: cage"
command -v chromium || command -v chromium-browser || echo "MISSING: chromium"
ls -l "$INSTALL_ROOT/scripts/kiosk-launch.sh" 2>/dev/null || echo "MISSING: kiosk-launch.sh"
echo

# nomodeset breaks Wayland/cage — drop it, keep other Cherry Trail stabilizers
if [[ -f /etc/default/grub ]] && grep -q nomodeset /etc/default/grub; then
  echo "Removing nomodeset from GRUB (needed for graphical kiosk)..."
  sed -i 's/ *nomodeset//g' /etc/default/grub
  update-grub || true
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends cage seatd chromium fonts-liberation

usermod -aG video,input,render "$KIOSK_USER" 2>/dev/null || usermod -aG video,input "$KIOSK_USER"
systemctl enable --now seatd.service 2>/dev/null || true
loginctl enable-linger "$KIOSK_USER" 2>/dev/null || true

if [[ ! -x "$INSTALL_ROOT/scripts/kiosk-launch.sh" ]]; then
  echo "ERROR: $INSTALL_ROOT/scripts/kiosk-launch.sh missing — remount USB and re-run 02-install-kiosk.sh" >&2
  exit 1
fi
chmod +x "$INSTALL_ROOT/scripts/kiosk-launch.sh"
chown -R "$KIOSK_USER:$KIOSK_USER" "$INSTALL_ROOT"

# Autologin on tty1 (recovery shell still available on tty2: Ctrl+Alt+F2)
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat >/etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Unit]
# Without this, tty1's getty can start (and this autologin can fire) before
# seatd is ready — cage then fails to acquire a seat, exits immediately, and
# since .bash_profile's exec is inside an interactive login shell, bash just
# drops back to a prompt instead of dying/retrying. Silent and easy to miss.
After=seatd.service
Wants=seatd.service

[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${KIOSK_USER} --noclear %I \$TERM
EOF

# Start kiosk from login shell on tty1 (most reliable on minimal Debian)
HOME_DIR="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
cat >"$HOME_DIR/.bash_profile" <<'EOF'
# HA kiosk autostart on tty1 only
if [ "$(tty 2>/dev/null)" = "/dev/tty1" ]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
  mkdir -p "$XDG_RUNTIME_DIR"
  chmod 700 "$XDG_RUNTIME_DIR" 2>/dev/null || true
  export WLR_RENDERER=pixman
  export WLR_NO_HARDWARE_CURSORS=1

  # seatd can still be starting up even with the systemd After=/Wants= above
  # (that orders unit *start*, not "seat actually ready to hand out"). Wait
  # briefly for its socket before the first launch attempt.
  for _ in $(seq 1 20); do
    [ -S /run/seatd.sock ] && break
    sleep 0.5
  done

  # Retry a few times with backoff — covers any other transient startup race
  # (DRM device not ready yet, etc.) instead of dropping to this shell on the
  # very first failure. Every attempt is logged so a persistent failure is
  # actually diagnosable instead of just "boots to a shell, no idea why".
  mkdir -p /opt/ha-kiosk/logs
  LOG=/opt/ha-kiosk/logs/kiosk-tty1.log
  echo "=== kiosk autostart $(date -Is) ===" >>"$LOG"
  ATTEMPT=0
  while [ "$ATTEMPT" -lt 5 ]; do
    ATTEMPT=$((ATTEMPT + 1))
    echo "--- attempt $ATTEMPT $(date -Is) ---" >>"$LOG"
    /usr/bin/cage -s -- /opt/ha-kiosk/scripts/kiosk-launch.sh >>"$LOG" 2>&1 && break
    echo "cage exited (attempt $ATTEMPT), retrying..." >>"$LOG"
    sleep 3
  done
  echo "Kiosk failed to start after $ATTEMPT attempt(s) — see $LOG"
  echo "Dropping to a login shell so you can diagnose (tail -f $LOG)."
fi
EOF
chown "$KIOSK_USER:$KIOSK_USER" "$HOME_DIR/.bash_profile"

# Also keep a systemd unit as backup (multi-user, no fragile tty7)
cat >/etc/systemd/system/ha-kiosk.service <<EOF
[Unit]
Description=Home Assistant Chromium kiosk (cage)
After=seatd.service network-online.target
Wants=seatd.service network-online.target

[Service]
Type=simple
User=${KIOSK_USER}
Group=${KIOSK_USER}
SupplementaryGroups=video input
Environment=XDG_RUNTIME_DIR=/run/user/${UID_NUM}
Environment=WLR_RENDERER=pixman
Environment=WLR_NO_HARDWARE_CURSORS=1
ExecStartPre=/bin/mkdir -p /run/user/${UID_NUM}
ExecStartPre=/bin/chown ${KIOSK_USER}:${KIOSK_USER} /run/user/${UID_NUM}
ExecStartPre=/bin/chmod 700 /run/user/${UID_NUM}
ExecStart=/usr/bin/cage -s -- ${INSTALL_ROOT}/scripts/kiosk-launch.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Prefer tty1 profile autostart; disable conflicting systemd kiosk to avoid double-start
systemctl daemon-reload
systemctl disable ha-kiosk.service 2>/dev/null || true
systemctl stop ha-kiosk.service 2>/dev/null || true
systemctl set-default multi-user.target
systemctl daemon-reload
systemctl restart getty@tty1.service 2>/dev/null || true

echo
echo "Fixed. Reboot now:"
echo "  reboot"
echo
echo "After reboot you should get the HA dashboard on tty1."
echo "If you need a text shell: Ctrl+Alt+F2 (login as ${KIOSK_USER})."
echo "Back to kiosk display: Ctrl+Alt+F1"
