#!/bin/bash
set -euxo pipefail
pkill -9 -f ffmpeg || true
pkill -9 -f 'v4l2-ctl' || true
sleep 1

echo '=== formats ==='
v4l2-ctl -d /dev/video0 --list-formats-ext 2>&1 | head -n 120 || true

echo '=== try stream ==='
rm -f /tmp/cam.raw /tmp/camtest.jpg
# AtomISP often wants YUV420 / NV12 at sensor native res
timeout -s KILL 12 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=900,pixelformat=NV12 \
  --stream-mmap --stream-count=1 --stream-to=/tmp/cam.raw 2>&1 || true
ls -la /tmp/cam.raw 2>&1 || true

timeout -s KILL 12 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=640,height=480,pixelformat=YUYV \
  --stream-mmap --stream-count=1 --stream-to=/tmp/cam.raw 2>&1 || true
ls -la /tmp/cam.raw 2>&1 || true

echo '=== dmesg ==='
dmesg | grep -iE 'atomisp|gc2235|shisp|css|firmware|timeout|ISP |error -' | tail -n 100 || true

echo '=== fw ==='
ls -la /lib/firmware/intel/ipu/ /lib/firmware/shisp* 2>&1 || true
echo DONE
