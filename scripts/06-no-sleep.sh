#!/usr/bin/env bash
# Keep Linx kiosk awake when plugged in (no blank / suspend / shutdown).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: su -   then: bash $0" >&2
  exit 1
fi

echo "Disabling suspend / hibernate / sleep targets..."
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || true

# logind: ignore idle, lid, power key sleep
mkdir -p /etc/systemd/logind.conf.d
cat >/etc/systemd/logind.conf.d/ha-kiosk-nosleep.conf <<'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
HandlePowerKey=ignore
IdleAction=ignore
IdleActionSec=infinity
EOF

# systemd sleep policy
mkdir -p /etc/systemd/sleep.conf.d
cat >/etc/systemd/sleep.conf.d/ha-kiosk-nosleep.conf <<'EOF'
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowSuspendThenHibernate=no
AllowHybridSleep=no
EOF

# Kernel console blanking off every boot
cat >/etc/systemd/system/ha-kiosk-noblank.service <<'EOF'
[Unit]
Description=Disable VT blanking for HA kiosk
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'setterm -blank 0 -powerdown 0 -powersave off </dev/tty1 2>/dev/null || true; echo 0 > /sys/module/kernel/parameters/consoleblank 2>/dev/null || true'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl enable ha-kiosk-noblank.service

# Runtime: block sleep while this unit is active (belt and braces)
cat >/etc/systemd/system/ha-kiosk-inhibit-sleep.service <<'EOF'
[Unit]
Description=Inhibit system sleep for HA kiosk
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/bin/systemd-inhibit --what=idle:sleep:handle-lid-switch --who=ha-kiosk --why="Wall panel kiosk" --mode=block /bin/sleep infinity
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl enable ha-kiosk-inhibit-sleep.service

# X11: keep display awake (used if startx / .xinitrc path)
KIOSK_USER="${KIOSK_USER:-kioskuser}"
HOME_DIR="$(getent passwd "$KIOSK_USER" | cut -d: -f6 || true)"
if [[ -n "$HOME_DIR" && -f "$HOME_DIR/.xinitrc" ]]; then
  if ! grep -q 'xset s off' "$HOME_DIR/.xinitrc" 2>/dev/null; then
    # prepend xset if missing
    tmp="$(mktemp)"
    {
      echo '#!/bin/sh'
      echo 'xset s off'
      echo 'xset -dpms'
      echo 'xset s noblank'
      grep -v -E '^(#!/bin/sh|xset )' "$HOME_DIR/.xinitrc" || true
    } >"$tmp"
    mv "$tmp" "$HOME_DIR/.xinitrc"
    chmod 755 "$HOME_DIR/.xinitrc"
    chown "$KIOSK_USER:$KIOSK_USER" "$HOME_DIR/.xinitrc"
  fi
fi

# Ensure xset lines exist for future X11 installs
mkdir -p /opt/ha-kiosk/scripts
cat >/opt/ha-kiosk/scripts/keep-awake-x11.sh <<'EOF'
#!/bin/sh
# Keep the kiosk panel awake — unless an intentional blank is active.
BLANK_FLAG="${BLANK_FLAG:-/opt/ha-kiosk/config/display_blanked}"
export DISPLAY="${DISPLAY:-:0}"
if [ -z "${XAUTHORITY:-}" ] && [ -f "$HOME/.Xauthority" ]; then
  export XAUTHORITY="$HOME/.Xauthority"
fi
xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true
while true; do
  if [ -f "$BLANK_FLAG" ]; then
    if xset q 2>/dev/null | grep -qi "Monitor is On"; then
      rm -f "$BLANK_FLAG"
      xset s off 2>/dev/null || true
      xset -dpms 2>/dev/null || true
      xset s noblank 2>/dev/null || true
    fi
  else
    xset s off 2>/dev/null || true
    xset -dpms 2>/dev/null || true
    xset s noblank 2>/dev/null || true
  fi
  sleep 5
done
EOF
chmod 755 /opt/ha-kiosk/scripts/keep-awake-x11.sh

systemctl daemon-reload
# Deliberately NOT restarting systemd-logind here: doing so tears down the
# active console session (whatever tty you're running this from), which
# restarts getty@tty1 — and if 02-install-kiosk.sh already ran, that
# immediately triggers the kiosk autologin mid-install, before later steps
# (07/09/10) have finished. The logind.conf.d changes above take effect on
# the next boot regardless, which every documented use of this script already
# ends with ("reboot recommended" below, and install.sh reboots at the end
# too) — so there's no upside to forcing it live, only the session-kill risk.
systemctl start ha-kiosk-noblank.service 2>/dev/null || true
systemctl start ha-kiosk-inhibit-sleep.service 2>/dev/null || true

# Apply blanking now
setterm -blank 0 -powerdown 0 -powersave off </dev/tty1 2>/dev/null || true
echo 0 >/sys/module/kernel/parameters/consoleblank 2>/dev/null || true

echo
echo "Sleep / blanking disabled."
echo "Reboot recommended: reboot"
echo
echo "If the panel still dims under Cage/Chromium, say so — we can force DPMS off in the compositor too."
