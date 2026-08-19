#!/bin/bash
# Probe whether AtomISP /dev/video0 can sustain a live encode.
set -euxo pipefail
/opt/ha-kiosk/scripts/load-atomisp.sh >/dev/null 2>&1 || true
pkill -9 -f 'ffmpeg|v4l2-ctl' 2>/dev/null || true
sleep 1

echo '=== formats ==='
v4l2-ctl -d /dev/video0 --list-formats-ext 2>&1 | head -n 40
v4l2-ctl -d /dev/video0 --get-fmt-video 2>&1 || true

echo '=== try ffmpeg v4l2 10s MJPEG ==='
rm -f /tmp/stream_probe.mjpeg /tmp/stream_probe.log
timeout -s KILL 12 ffmpeg -hide_banner -loglevel info \
  -f v4l2 -input_format nv12 -video_size 1600x1200 -framerate 10 -i /dev/video0 \
  -vf 'crop=1584:1184:0:0,scale=792:592' \
  -c:v mjpeg -q:v 8 -f mjpeg /tmp/stream_probe.mjpeg \
  > /tmp/stream_probe.log 2>&1 || true
ls -la /tmp/stream_probe.mjpeg 2>/dev/null || true
tail -n 40 /tmp/stream_probe.log || true

echo '=== try raw v4l2-ctl stream 8s ==='
rm -f /tmp/stream_probe.raw
timeout -s KILL 8 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=30 --stream-to=/tmp/stream_probe.raw 2>&1 || true
ls -la /tmp/stream_probe.raw 2>/dev/null || true
