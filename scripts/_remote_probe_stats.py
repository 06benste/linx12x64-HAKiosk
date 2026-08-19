#!/usr/bin/env python3
import sys
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password="kiosk", timeout=15, allow_agent=False, look_for_keys=False)
script = r"""
echo '=== thermal ==='
ls /sys/class/thermal/ 2>/dev/null
for t in /sys/class/thermal/thermal_zone*; do
  [ -d "$t" ] || continue
  echo "$(basename $t) type=$(cat $t/type 2>/dev/null) temp=$(cat $t/temp 2>/dev/null)"
done
echo '=== hwmon ==='
for h in /sys/class/hwmon/hwmon*; do
  [ -d "$h" ] || continue
  name=$(cat $h/name 2>/dev/null)
  echo "-- $name --"
  ls $h | head
  for f in $h/temp*_input $h/fan*_input $h/in*_input; do
    [ -f "$f" ] && echo "$(basename $f)=$(cat $f)"
  done
done
echo '=== cpu freq ==='
ls /sys/devices/system/cpu/cpu0/cpufreq 2>/dev/null | head
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null
nproc
echo '=== disk ==='
df -h / /boot 2>/dev/null
echo '=== net ==='
cat /sys/class/net/wlan0/statistics/rx_bytes 2>/dev/null
cat /sys/class/net/wlan0/statistics/tx_bytes 2>/dev/null
cat /proc/net/wireless 2>/dev/null
echo '=== iio sensors ==='
ls /sys/bus/iio/devices 2>/dev/null || echo none
for d in /sys/bus/iio/devices/iio:device*; do
  [ -d "$d" ] || continue
  echo "-- $(cat $d/name 2>/dev/null) --"
  ls $d | head -n 20
done
echo '=== input accel ==='
cat /proc/bus/input/devices 2>/dev/null | head -n 80
echo '=== backlight already known ==='
cat /sys/class/backlight/intel_backlight/actual_brightness 2>/dev/null
echo '=== load/mem/swap ==='
cat /proc/loadavg
free -m | head -n 3
swapon --show 2>/dev/null
echo '=== processes ==='
ps -eo rss,comm --sort=-rss | head -n 8
"""
sftp = c.open_sftp()
with sftp.file("/tmp/stats-probe.sh", "w") as f:
    f.write(script)
sftp.chmod("/tmp/stats-probe.sh", 0o755)
sftp.close()
stdin, stdout, stderr = c.exec_command("bash /tmp/stats-probe.sh", timeout=25)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print(stdout.read().decode())
c.close()
