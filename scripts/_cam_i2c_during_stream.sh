#!/bin/bash
set -euxo pipefail
modprobe i2c-dev || true
pkill -9 -f v4l2-ctl || true
sleep 1

# Map GCTI2355 devices to i2c adapters
python3 - <<'PY'
from pathlib import Path
for d in sorted(Path('/sys/bus/i2c/devices').glob('i2c-GCTI2355:*')):
    # device path like .../i2c-N/i2c-GCTI2355:00
    real = d.resolve() if d.is_symlink() else d
    parts = str(real).split('/')
    bus = None
    for p in parts:
        if p.startswith('i2c-') and p[4:].isdigit():
            bus = int(p[4:])
    name = (d/'name').read_text().strip() if (d/'name').exists() else d.name
    print(f'{d.name} name={name} bus={bus} path={real}')
PY

echo '=== power on via v4l2 stream in background, then i2c dump ==='
dmesg -C
# Start a long stream in background so sensor stays powered
timeout -s KILL 25 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1584,height=1184,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=100 --stream-to=/dev/null &
VPID=$!
sleep 2

# Find buses again and dump key regs
for bus in $(ls /dev/i2c-* 2>/dev/null | sed 's|/dev/i2c-||'); do
  echo "scan bus $bus"
  # try read id at 0x3c
  H=$(i2cget -y "$bus" 0x3c 0xf0 2>/dev/null || true)
  L=$(i2cget -y "$bus" 0x3c 0xf1 2>/dev/null || true)
  if [[ -n "$H" ]]; then
    echo "bus $bus 0x3c id=$H $L"
    # switch to page 3 and read stream reg 0x10
    i2cset -y "$bus" 0x3c 0xfe 0x03
    STREAM=$(i2cget -y "$bus" 0x3c 0x10 2>/dev/null || echo fail)
    echo "page3 reg0x10(stream)=$STREAM"
    MIPI01=$(i2cget -y "$bus" 0x3c 0x01 2>/dev/null || echo fail)
    echo "page3 reg0x01(lane)=$MIPI01"
    i2cset -y "$bus" 0x3c 0xfe 0x00
    # dump a few page0 regs
    for r in 0xf7 0xf8 0xf9 0xfa 0x03 0x04 0x0d 0x0e 0x0f 0x10 0x95 0x96 0x97 0x98; do
      v=$(i2cget -y "$bus" 0x3c $r 2>/dev/null || echo xx)
      echo -n "p0[$r]=$v "
    done
    echo
  fi
done

wait $VPID || true
echo '=== dmesg sensor/stream ==='
dmesg | grep -iE 'gc2235|stream|s_stream|error|fail|CSS|FPS' | tail -n 50
echo DUMP_OK
