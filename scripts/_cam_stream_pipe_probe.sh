#!/bin/bash
set -euxo pipefail
/opt/ha-kiosk/scripts/load-atomisp.sh >/dev/null 2>&1 || true
pkill -9 -f 'ffmpeg|v4l2-ctl' 2>/dev/null || true
sleep 2

WB_R=1.348; WB_G=0.910; WB_B=1.001
CONTRAST=1.021; SAT=1.080; BRIGHT=-0.0233
VF="crop=1584:1184:0:0,scale=792:592,colorchannelmixer=rr=${WB_R}:gg=${WB_G}:bb=${WB_B},eq=contrast=${CONTRAST}:saturation=${SAT}:brightness=${BRIGHT}"

echo '=== pipe v4l2-ctl -> ffmpeg (stride-aware) ==='
rm -f /tmp/live.mjpeg /tmp/live.log
# Produce raw NV12 with stride 1600; ffmpeg reads 1600x1184 then crops.
timeout -s KILL 15 bash -c "
  v4l2-ctl -d /dev/video0 \
    --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
    --stream-mmap=4 --stream-count=0 --stream-to=- 2>/tmp/v4l2_stream.err \
  | ffmpeg -hide_banner -loglevel info -y \
      -f rawvideo -pix_fmt nv12 -video_size 1600x1184 -framerate 8 -i - \
      -vf '$VF' -c:v mjpeg -q:v 7 -f mjpeg /tmp/live.mjpeg
" > /tmp/live.log 2>&1 || true

ls -la /tmp/live.mjpeg /tmp/v4l2_stream.err 2>/dev/null || true
echo '--- live.log ---'
tail -n 50 /tmp/live.log || true
echo '--- v4l2 err ---'
cat /tmp/v4l2_stream.err 2>/dev/null | tail -n 20 || true

# Count JPEG markers roughly
python3 - <<'PY'
from pathlib import Path
p=Path('/tmp/live.mjpeg')
if not p.exists():
  print('no mjpeg'); raise SystemExit
b=p.read_bytes()
print('bytes', len(b))
# SOI markers
n=b.count(b'\xff\xd8')
print('jpeg_frames_approx', n)
PY
