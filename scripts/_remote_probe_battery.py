#!/usr/bin/env python3
import sys
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password="kiosk", timeout=15, allow_agent=False, look_for_keys=False)
script = r"""
echo '=== power_supply ==='
ls -la /sys/class/power_supply/ 2>/dev/null || echo none
for d in /sys/class/power_supply/*; do
  [ -d "$d" ] || continue
  echo "-- $(basename "$d") --"
  for f in type status online present capacity capacity_level voltage_now current_now charge_now charge_full energy_now energy_full manufacturer model_name serial_number technology; do
    [ -f "$d/$f" ] && echo "$f=$(cat "$d/$f" 2>/dev/null)"
  done
done
echo '=== upower ==='
command -v upower >/dev/null && upower -e && upower -d | head -n 80 || echo no-upower
echo '=== acpi ==='
command -v acpi >/dev/null && acpi -V || echo no-acpi
"""
sftp = c.open_sftp()
with sftp.file("/tmp/batt-probe.sh", "w") as f:
    f.write(script)
sftp.chmod("/tmp/batt-probe.sh", 0o755)
sftp.close()
stdin, stdout, stderr = c.exec_command("bash /tmp/batt-probe.sh", timeout=20)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print(stdout.read().decode())
print(stderr.read().decode()[:500])
c.close()
