#!/bin/bash
set -euxo pipefail
pkill -9 -f 'ffmpeg|v4l2-ctl' || true
sleep 1
rm -f /tmp/cam.raw /tmp/camtest.jpg /tmp/camtest.ppm

echo '=== set fmt exact ==='
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1600,height=1200,pixelformat=NV12 --get-fmt-video

echo '=== stream 1600x1200 NV12 ==='
timeout -s KILL 15 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=3 --stream-to=/tmp/cam.raw 2>&1 || true
ls -la /tmp/cam.raw 2>&1 || true

echo '=== stream 1584x884 YUYV ==='
timeout -s KILL 15 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1584,height=884,pixelformat=YUYV \
  --stream-mmap=4 --stream-count=3 --stream-to=/tmp/cam.raw 2>&1 || true
ls -la /tmp/cam.raw 2>&1 || true

echo '=== dmesg delta ==='
dmesg | grep -iE 'atomisp|gc2235|css|timeout|stream|error|fail|FPS' | tail -n 40

# Convert if we got bytes
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw size=$SZ"
if [[ "$SZ" -gt 1000 ]]; then
  # NV12 1600x1200 = 1600*1200*1.5 = 2880000
  ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1600x1200 -i /tmp/cam.raw -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 10 || true
  ls -la /tmp/camtest.jpg || true
fi
echo DONE
