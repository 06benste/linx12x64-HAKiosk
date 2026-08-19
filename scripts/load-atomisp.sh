#!/bin/bash
set -e
modprobe atomisp_gmin_platform || true
# Give PCI device a moment after gmin
sleep 1
modprobe atomisp || true
sleep 2
modprobe atomisp-gc2235 || true
sleep 2
# If sensors loaded before ISP and failed, try once more after ISP is up
if ! dmesg | tail -n 200 | grep -q 'detect gc2235/gc2355 success'; then
  modprobe -r atomisp-gc2235 2>/dev/null || true
  sleep 1
  modprobe atomisp-gc2235 || true
  sleep 2
fi
ls -la /dev/video* /dev/media* 2>&1 || true
dmesg | grep -iE 'atomisp|gc2235|GCTI|shisp|no camera|detect gc' | tail -n 40 || true
