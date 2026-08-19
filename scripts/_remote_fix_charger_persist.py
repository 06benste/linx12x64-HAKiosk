#!/usr/bin/env python3
"""Persist AXP288 input_current_limit bump so battery can charge on weak SDP detect."""
from __future__ import annotations

import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"

REMOTE = r"""#!/bin/bash
set -euxo pipefail

# Try a higher limit now
P=/sys/class/power_supply/axp288_charger
for v in 2000000 2400000 1500000; do
  if echo "$v" > "$P/input_current_limit" 2>/dev/null; then
    echo "live set $v"
    break
  fi
done
echo "icl now $(cat $P/input_current_limit)"
sleep 3
B=/sys/class/power_supply/axp288_fuel_gauge
echo "status=$(cat $B/status) cap=$(cat $B/capacity) I=$(cat $B/current_now) V=$(cat $B/voltage_now)"

install -d /opt/ha-kiosk/scripts
cat > /opt/ha-kiosk/scripts/fix-charger-limit.sh <<'EOF'
#!/bin/bash
# AXP288 often classifies the wall wart as SDP @ 500mA. Chromium+X11 draws ~1A,
# so the battery discharges while "plugged in" and the tablet hard-cuts overnight.
set -e
P=/sys/class/power_supply/axp288_charger/input_current_limit
[ -f "$P" ] || exit 0
# Prefer 2A; fall back if rejected
for v in 2000000 1500000 900000; do
  if echo "$v" > "$P" 2>/dev/null; then
    logger -t ha-kiosk-charger "set input_current_limit=$v (was SDP-starved)"
    exit 0
  fi
done
logger -t ha-kiosk-charger "failed to raise input_current_limit"
exit 1
EOF
chmod 755 /opt/ha-kiosk/scripts/fix-charger-limit.sh

cat > /etc/systemd/system/ha-kiosk-charger-limit.service <<'EOF'
[Unit]
Description=Raise AXP288 USB input current limit for kiosk charging
After=sysinit.target
DefaultDependencies=no

[Service]
Type=oneshot
ExecStart=/opt/ha-kiosk/scripts/fix-charger-limit.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Also re-apply via udev when power_supply appears
cat > /etc/udev/rules.d/99-ha-kiosk-axp288-charge.rules <<'EOF'
ACTION=="add|change", SUBSYSTEM=="power_supply", KERNEL=="axp288_charger", RUN+="/opt/ha-kiosk/scripts/fix-charger-limit.sh"
EOF

systemctl daemon-reload
systemctl enable --now ha-kiosk-charger-limit.service
udevadm control --reload
sleep 2
echo "--- verify ---"
systemctl status ha-kiosk-charger-limit.service --no-pager -l | head -20
echo "icl=$(cat $P/input_current_limit)"
echo "status=$(cat $B/status) I=$(cat $B/current_now) cap=$(cat $B/capacity)"
echo OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/fix-chg.sh", "w") as f:
        f.write(REMOTE)
    sftp.chmod("/tmp/fix-chg.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/fix-chg.sh", timeout=40
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-1200:])
    c.close()


if __name__ == "__main__":
    main()
