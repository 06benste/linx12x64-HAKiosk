#!/usr/bin/env python3
import paramiko, sys
HOST, PASS = "192.168.8.201", "kiosk"
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
cmd = r"""
echo kiosk | sudo -S -p '' bash -lc '
systemctl status ha-kiosk-camera-stream --no-pager -l | head -n 40
echo === journal ===
journalctl -u ha-kiosk-camera-stream -n 40 --no-pager
echo === procs ===
ps aux | grep -E "ffmpeg|v4l2-ctl|camera-stream" | grep -v grep
echo === manual ffmpeg test ===
# kill stream briefly
systemctl stop ha-kiosk-camera-stream
pkill -9 -f "v4l2-ctl --stream" || true
pkill -9 -f "ffmpeg.*rawvideo" || true
sleep 1
/opt/ha-kiosk/scripts/load-atomisp.sh >/dev/null 2>&1 || true
rm -f /tmp/t_plain.mjpeg /tmp/t_grad.jpg
mkfifo /tmp/t_plain.mjpeg
# open fifo rdwr in background reader
python3 - <<PY &
import os, time
fd=os.open("/tmp/t_plain.mjpeg", os.O_RDWR)
n=0
t=time.time()
while time.time()-t < 8:
  b=os.read(fd, 65536)
  if b: n+=len(b)
print("plain_bytes", n)
os.close(fd)
PY
sleep 0.2
timeout 8 bash -c "
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1600,height=1200,pixelformat=NV12 --stream-mmap=3 --stream-count=30 --stream-to=- \
| ffmpeg -hide_banner -loglevel info -f rawvideo -pix_fmt nv12 -video_size 1600x1184 -framerate 8 -i pipe:0 \
  -filter_complex \"[0:v]crop=1584:1184:0:0,scale=640:480,split=2[pl][g0];[g0]eq=contrast=1.04:saturation=1.05:brightness=0:gamma=1[gr]\" \
  -map [gr] -frames:v 1 -q:v 5 /tmp/t_grad.jpg \
  -map [pl] -f mjpeg /tmp/t_plain.mjpeg
" 2>/tmp/ff_err.txt || true
wait || true
ls -l /tmp/t_grad.jpg /tmp/t_plain.mjpeg 2>/dev/null || true
echo === ffmpeg stderr ===
tail -n 40 /tmp/ff_err.txt
systemctl start ha-kiosk-camera-stream
'
"""
_,o,_=c.exec_command(cmd, timeout=90, get_pty=True)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stdout.write(o.read().decode("utf-8","replace"))
c.close()
