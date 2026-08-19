#!/bin/bash
set -euxo pipefail
pkill -9 -f 'ffmpeg|v4l2-ctl' || true
sleep 1

echo '=== topology before ==='
media-ctl -d /dev/media0 -p | head -n 80

echo '=== configure pipeline ==='
# Configure sensor -> CSI2 -> ISP formats for RAW10 1600x1200
media-ctl -d /dev/media0 -V '"gc2235 0-003c":0[fmt:SGRBG10_1X10/1600x1200@1/30]' || true
media-ctl -d /dev/media0 -V '"ATOM ISP CSI2-port0":0[fmt:SGRBG10_1X10/1600x1200]' || true
media-ctl -d /dev/media0 -V '"ATOM ISP CSI2-port0":1[fmt:SGRBG10_1X10/1600x1200]' || true
media-ctl -d /dev/media0 -V '"Atom ISP":0[fmt:SGRBG10_1X10/1600x1200]' || true
media-ctl -d /dev/media0 -V '"Atom ISP":1[fmt:SGRBG10_1X10/1600x1200]' || true

# Also try SBGGR10
media-ctl -d /dev/media0 -V '"gc2235 0-003c":0[fmt:SBGGR10_1X10/1600x1200@1/30]' || true
media-ctl -d /dev/media0 -V '"ATOM ISP CSI2-port0":0[fmt:SBGGR10_1X10/1600x1200]' || true

echo '=== topology after ==='
media-ctl -d /dev/media0 -p | head -n 90

echo '=== stream ==='
rm -f /tmp/cam.raw /tmp/camtest.jpg
dmesg -C
timeout -s KILL 20 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=2 --stream-to=/tmp/cam.raw 2>&1 || true
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw=$SZ"
dmesg | tail -n 40
if [[ "$SZ" -gt 100000 ]]; then
  ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1600x1200 -i /tmp/cam.raw -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 8
  ls -la /tmp/camtest.jpg
fi
echo DONE
