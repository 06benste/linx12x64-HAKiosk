#!/bin/bash
set -euxo pipefail
pkill -9 -f 'ffmpeg|v4l2-ctl' || true
sleep 1
rm -f /tmp/cam.raw /tmp/camtest.jpg
dmesg -C

echo '=== try native ISP size 1584x1184 ==='
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1584,height=1184,pixelformat=NV12 --get-fmt-video
timeout -s KILL 30 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1584,height=1184,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=3 --stream-to=/tmp/cam.raw 2>&1 || true
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw=$SZ"
dmesg | tail -n 50

# Also try YUYV
if [[ "$SZ" -lt 1000 ]]; then
  pkill -9 -f v4l2-ctl || true
  sleep 2
  dmesg -C
  timeout -s KILL 30 v4l2-ctl -d /dev/video0 \
    --set-fmt-video=width=1584,height=1184,pixelformat=YUYV \
    --stream-mmap=4 --stream-count=3 --stream-to=/tmp/cam.raw 2>&1 || true
  SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
  echo "raw2=$SZ"
  dmesg | tail -n 40
fi

if [[ "$SZ" -gt 100000 ]]; then
  ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1584x1184 -i /tmp/cam.raw -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 10 || \
  ffmpeg -y -f rawvideo -pix_fmt yuyv422 -s 1584x1184 -i /tmp/cam.raw -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 10
  ls -la /tmp/camtest.jpg
fi
echo DONE
