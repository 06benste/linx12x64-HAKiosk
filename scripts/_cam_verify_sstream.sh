#!/bin/bash
set -euxo pipefail
# Enable verbose logging on sensor + ISP; verify s_stream/power
echo 2 > /sys/module/atomisp/parameters/dbg_level || true
echo 'module atomisp_gc2235 +pfl' > /sys/kernel/debug/dynamic_debug/control 2>/dev/null || true
echo 'file atomisp-gc2235.c +pfl' > /sys/kernel/debug/dynamic_debug/control 2>/dev/null || true
# Match whatever the module filename is
grep -i gc2235 /sys/kernel/debug/dynamic_debug/control | head -n 20 || true
# Enable all gc2235 prints
echo 'module atomisp_gc2235 =p' > /sys/kernel/debug/dynamic_debug/control || true

pkill -9 -f v4l2-ctl || true
sleep 1
dmesg -C

# Show power state before
for d in /sys/bus/i2c/devices/i2c-GCTI2355:00 /sys/bus/i2c/devices/i2c-GCTI2355:01; do
  echo "== $d =="
  cat "$d/power/runtime_status" 2>/dev/null || true
  cat "$d/power/control" 2>/dev/null || true
  # clock enable counts
done
grep pmc_plt_clk_[24] /sys/kernel/debug/clk/clk_summary || true

timeout -s KILL 12 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1584,height=1184,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=1 2>&1 || true

echo '=== during/after clocks ==='
grep pmc_plt_clk_[24] /sys/kernel/debug/clk/clk_summary || true

echo '=== dmesg (sensor path) ==='
dmesg | grep -iE 'gc2235|s_stream|s_power|power|stream_on|write_reg|error|fail|GCTI' | tail -n 80

# Try userspace i2c while forcing runtime resume
echo on > /sys/bus/i2c/devices/i2c-GCTI2355:00/power/control || true
echo on > /sys/bus/i2c/devices/i2c-GCTI2355:01/power/control || true
# Prefer kernel i2c transfer via a tiny program? just try i2cget after forcing
sleep 1
# Power via v4l2 open+stream again briefly while reading from correct buses 0 and 1
timeout -s KILL 8 bash -c '
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1584,height=1184,pixelformat=NV12 --stream-mmap=4 --stream-count=50 --stream-to=/dev/null &
sleep 1
for bus in 0 1; do
  echo BUS $bus
  i2cget -y $bus 0x3c 0xf0; i2cget -y $bus 0x3c 0xf1
  i2cset -y $bus 0x3c 0xfe 0x03
  echo -n stream_reg=; i2cget -y $bus 0x3c 0x10
  i2cset -y $bus 0x3c 0xfe 0x00
  echo -n f7=; i2cget -y $bus 0x3c 0xf7
  echo -n f8=; i2cget -y $bus 0x3c 0xf8
  echo -n f9=; i2cget -y $bus 0x3c 0xf9
done
wait
' 2>&1 || true

echo POWER_OK
