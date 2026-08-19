#!/bin/bash
# Deep camera stream diagnostics on Linx tablet
set -euxo pipefail
K=$(uname -r)

echo '=== firmware variants ==='
mkdir -p /lib/firmware/intel/ipu
# Ensure all known shisp names exist (same blob for now)
for n in shisp_2401a0_v21.bin shisp_2401a0_legacy_v21.bin shisp_2400b0_v21.bin; do
  if [[ ! -e /lib/firmware/intel/ipu/$n ]]; then
    ln -sfn /lib/firmware/shisp_2401a0_v21.bin /lib/firmware/intel/ipu/$n
  fi
  ls -la /lib/firmware/intel/ipu/$n
done

echo '=== enable dyndbg ==='
mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug
echo 'module atomisp +p' > /sys/kernel/debug/dynamic_debug/control 2>/dev/null || true
echo 'module atomisp_gmin_platform +p' > /sys/kernel/debug/dynamic_debug/control 2>/dev/null || true
echo 'module atomisp_gc2235 +p' > /sys/kernel/debug/dynamic_debug/control 2>/dev/null || true
# firmware loader
echo 'file firmware_class.c +p' > /sys/kernel/debug/dynamic_debug/control 2>/dev/null || true

echo '=== i2c adapters / gc2355 ==='
i2cdetect -l || true
# Front cam is on I2C1 typically addr 0x3c
dmesg | grep -i 'GCTI2355' | head -n 20 || true

echo '=== gpio for cams ==='
for g in /sys/class/gpio/gpiochip*/label; do echo "$g=$(cat $g)"; done 2>/dev/null | head
find /sys/devices -name 'gpiod:*' 2>/dev/null | head -n 20 || true
# Show consumer gpios for the i2c devices
for d in /sys/bus/i2c/devices/i2c-GCTI2355:*/; do
  echo "== $d =="
  ls -la "$d" 2>/dev/null | head
  cat "$d"/name 2>/dev/null || true
  cat "$d"/of_node/name 2>/dev/null || true
  ls "$d"/power 2>/dev/null || true
  # status
  cat "$d"/uevent 2>/dev/null || true
done

pkill -9 -f 'v4l2-ctl|ffmpeg' || true
sleep 1
dmesg -C

echo '=== stream attempt with dyndbg ==='
timeout -s KILL 20 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1584,height=1184,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=1 --stream-to=/tmp/cam.raw 2>&1 || true
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw=$SZ"

echo '=== dmesg during stream ==='
dmesg | tail -n 120

echo '=== try read sensor id while idle (power may be off) ==='
# Find bus numbers for GCTI2355
for d in /sys/bus/i2c/devices/i2c-GCTI2355:*/; do
  bus=$(basename "$(dirname "$(readlink -f "$d/driver" 2>/dev/null || echo)" 2>/dev/null)" 2>/dev/null || true)
  name=$(cat "$d/name" 2>/dev/null || basename "$d")
  # uevent has OF_FULLNAME etc; get adapter from path
  adapter=$(echo "$d" | grep -oE 'i2c-[0-9]+' | head -1 || true)
  echo "dev=$d adapter_guess=$adapter name=$name"
done
# From earlier ACPI: I2C1.CAM7 and I2C2.CAMA, addr 0x3c
for bus in 1 2 3 4 5 6 7 8; do
  if [[ -e /dev/i2c-$bus ]]; then
    echo -n "bus $bus @0x3c id: "
    # page0, read 0xf0/0xf1 — may fail if powered down
    i2cget -y $bus 0x3c 0xf0 2>/dev/null || echo 'fail'
    i2cget -y $bus 0x3c 0xf1 2>/dev/null || true
  fi
done

echo '=== module params / atomisp ==='
modinfo atomisp | grep -iE 'parm|firmware|depend' || true
ls /sys/module/atomisp/parameters 2>/dev/null || true
for f in /sys/module/atomisp/parameters/*; do echo -n "$(basename $f)="; cat $f; done 2>/dev/null || true

echo DIAG_OK
