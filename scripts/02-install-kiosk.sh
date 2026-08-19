#!/usr/bin/env bash
# Minimal Debian HA kiosk: cage + Chromium + autologin.
set -euo pipefail

HA_URL="${1:-}"
KIOSK_USER="${KIOSK_USER:-kioskuser}"
INSTALL_ROOT="/opt/ha-kiosk"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0 'http://homeassistant.local:8123/...'" >&2
  exit 1
fi

if [[ -z "$HA_URL" ]]; then
  echo "No HA URL given — the tablet will show the on-screen setup wizard on first boot."
  echo "(Or pre-configure it now: sudo bash $0 'http://homeassistant.local:8123/dashboard-kiosk')"
fi

if ! id "$KIOSK_USER" &>/dev/null; then
  echo "User '$KIOSK_USER' does not exist. Create it during Debian install or: adduser $KIOSK_USER" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  cage \
  seatd \
  chromium \
  fonts-liberation \
  network-manager \
  sudo \
  ca-certificates

usermod -aG video,input,render "$KIOSK_USER" 2>/dev/null || usermod -aG video,input "$KIOSK_USER"
systemctl enable --now seatd.service 2>/dev/null || true

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$INSTALL_ROOT/scripts" "$INSTALL_ROOT/chromium-extension" "$INSTALL_ROOT/chromium-profile"
install -m 755 "$ROOT/scripts/kiosk-launch.sh" "$INSTALL_ROOT/scripts/kiosk-launch.sh"
install -m 755 "$ROOT/scripts/01-wifi-firmware.sh" "$INSTALL_ROOT/scripts/01-wifi-firmware.sh" 2>/dev/null || true
install -m 755 "$ROOT/scripts/03-fix-gpu.sh" "$INSTALL_ROOT/scripts/03-fix-gpu.sh" 2>/dev/null || true
if [[ -n "$HA_URL" ]]; then
  printf '%s\n' "$HA_URL" > "$INSTALL_ROOT/url"
fi

# Setup wizard: shown by kiosk-launch.sh whenever no URL is configured, and
# reachable later via the power drawer's "Tablet Setup" button (Home
# Assistant / Wi-Fi / MQTT / Cameras tabs all live on this one page).
mkdir -p "$INSTALL_ROOT/scripts/static"
install -m 755 "$ROOT/scripts/setup-wizard.py" "$INSTALL_ROOT/scripts/setup-wizard.py"
install -m 644 "$ROOT/scripts/static/setup.html" "$INSTALL_ROOT/scripts/static/setup.html"
install -m 644 "$ROOT/scripts/ha-kiosk-setup.service" /etc/systemd/system/ha-kiosk-setup.service
systemctl daemon-reload
systemctl enable --now ha-kiosk-setup.service

# Cherry Trail GPU hang mitigations (flashing lines / crash)
if [[ -f "$ROOT/scripts/03-fix-gpu.sh" ]]; then
  bash "$ROOT/scripts/03-fix-gpu.sh" || echo "WARNING: GPU fix script failed — run it manually later"
fi


# HA login credentials → Chromium autofill extension
CRED_FILE=""
for candidate in "$ROOT/credentials.env" "$ROOT/ha-credentials.env"; do
  if [[ -f "$candidate" ]]; then
    CRED_FILE="$candidate"
    break
  fi
done

HA_USER_VAL=""
HA_PASS_VAL=""
if [[ -n "$CRED_FILE" ]]; then
  # Parse KEY=VAL lines (ignore comments / blanks); tolerate Windows CRLF
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    case "$key" in
      HA_USER) HA_USER_VAL="$val" ;;
      HA_PASS) HA_PASS_VAL="$val" ;;
    esac
  done < "$CRED_FILE"
  install -m 600 "$CRED_FILE" "$INSTALL_ROOT/credentials.env"
fi

if [[ -d "$ROOT/chromium-extension" ]]; then
  cp -a "$ROOT/chromium-extension/." "$INSTALL_ROOT/chromium-extension/"
fi

json_escape() {
  # Escape for a JSON string literal
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/'"$(printf '\t')"'/\\t/g'
}

if [[ -n "$HA_USER_VAL" && -n "$HA_PASS_VAL" ]]; then
  cat >"$INSTALL_ROOT/chromium-extension/config.js" <<EOF
window.HA_KIOSK_AUTH = {
  user: "$(json_escape "$HA_USER_VAL")",
  pass: "$(json_escape "$HA_PASS_VAL")"
};
EOF
  chmod 600 "$INSTALL_ROOT/chromium-extension/config.js"
  echo "HA autofill enabled for user '${HA_USER_VAL}'"
else
  echo "WARNING: No credentials.env found — HA login will not autofill."
  echo "         Prefer Trusted Networks on the HA server, or add credentials.env"
fi

chown -R "$KIOSK_USER:$KIOSK_USER" "$INSTALL_ROOT"

# Ignore lid / suspend (keyboard cover / kickstand quirks on Linx)
mkdir -p /etc/systemd/logind.conf.d
cat >/etc/systemd/logind.conf.d/ha-kiosk.conf <<'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
IdleAction=ignore
EOF

loginctl enable-linger "$KIOSK_USER" 2>/dev/null || true

# Autologin on tty1, launching the kiosk directly from that login shell.
#
# The alternative — a systemd service pinned to TTYPath=/dev/tty7 under
# graphical.target — looks reliable but isn't: nothing actually switches the
# active VT to tty7 when the service starts, so the physical screen just
# keeps showing tty1's own login (autologin or not) while cage silently runs,
# invisible, on tty7 in the background. Launching cage directly on tty1 (the
# tty that's actually displayed at boot) avoids that VT-switch problem
# entirely — this is the same fix scripts/04-fix-kiosk-autostart.sh applies
# after the fact; it's just the default now instead of a manual recovery step.
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

# Backup systemd unit — not enabled by default (tty1 .bash_profile above is
# primary). Lets you `systemctl start ha-kiosk` manually if ever useful, and
# is what the power drawer / setup wizard's restart-kiosk helper falls back
# to restarting getty@tty1.service for, since this unit normally stays inactive.
UID_NUM="$(id -u "$KIOSK_USER")"
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

systemctl set-default multi-user.target

# Console blanking off
cat >/etc/systemd/system/ha-kiosk-noblank.service <<'EOF'
[Unit]
Description=Disable console blanking for HA kiosk
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'setterm -blank 0 -powerdown 0 </dev/tty1 || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl enable ha-kiosk-noblank.service

# Weekly reboot Sunday 04:00
cat >/etc/systemd/system/ha-kiosk-reboot.timer <<'EOF'
[Unit]
Description=Weekly reboot for HA kiosk tablet

[Timer]
OnCalendar=Sun *-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
cat >/etc/systemd/system/ha-kiosk-reboot.service <<'EOF'
[Unit]
Description=Reboot HA kiosk tablet

[Service]
Type=oneshot
ExecStart=/sbin/reboot
EOF
systemctl enable ha-kiosk-reboot.timer

systemctl daemon-reload

echo
echo "Kiosk installed for user '${KIOSK_USER}'."
if [[ -n "$HA_URL" ]]; then
  echo "URL: ${HA_URL}"
  if [[ -n "${HA_USER_VAL:-}" ]]; then
    echo "HA autofill user: ${HA_USER_VAL}"
  fi
else
  echo "No URL configured — first boot will show the on-screen setup wizard."
fi
echo "Reboot to start: sudo reboot"
echo "Change URL later: on the tablet, use the control drawer's 'Tablet Setup' button, or:"
echo "  echo 'http://...' | sudo tee /opt/ha-kiosk/url && sudo systemctl restart getty@tty1"
echo "SSH: ssh ${KIOSK_USER}@$(hostname)"
