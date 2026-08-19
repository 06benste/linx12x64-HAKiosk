#!/bin/bash
# Force-install AtomISP DKMS + GC2355 ACPI/chip-id patch on Linx 12X64.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
K=$(uname -r)

echo "=== install build deps for $K ==="
apt-get update -qq
apt-get install -y -qq \
  build-essential dkms git curl ca-certificates v4l-utils \
  "linux-headers-${K}" || apt-get install -y -qq linux-headers-amd64

echo "=== ISP firmware ==="
mkdir -p /lib/firmware
if [[ ! -f /lib/firmware/shisp_2401a0_v21.bin ]]; then
  curl -fsSL -o /lib/firmware/shisp_2401a0_v21.bin \
    'https://github.com/intel-aero/meta-intel-aero-base/raw/master/recipes-kernel/linux/linux-yocto/shisp_2401a0_v21.bin' \
    || curl -fsSL -o /lib/firmware/shisp_2401a0_v21.bin \
    'https://raw.githubusercontent.com/intel-aero/meta-intel-aero-base/master/recipes-kernel/linux/linux-yocto/shisp_2401a0_v21.bin'
fi
ls -la /lib/firmware/shisp_2401a0_v21.bin /lib/firmware/intel/irci* 2>/dev/null || true

echo "=== clone atomisp DKMS ==="
rm -rf /usr/src/atomisp-dkms-src
git clone --depth 1 https://github.com/EasyNetDev/atomisp-6.10-dkms.git /usr/src/atomisp-dkms-src
cd /usr/src/atomisp-dkms-src

patch_gc2235() {
  local GC="$1"
  [[ -f "$GC" ]] || return 0
  if ! grep -q 'GCTI2355' "$GC"; then
    sed -i 's/{ "INT33F8" },/{ "INT33F8" },\n\t{ "GCTI2355" },\n\t{ "INT2355" },/' "$GC"
  fi
  python3 - "$GC" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
t = p.read_text()
old = (
    "\tif (id != GC2235_ID) {\n"
    "\t\tdev_err(&client->dev, \"sensor ID error, 0x%x\\n\", id);\n"
    "\t\treturn -ENODEV;\n"
    "\t}\n"
    "\n"
    "\tdev_info(&client->dev, \"detect gc2235 success\\n\");"
)
new = (
    "\tif (id != GC2235_ID && id != 0x2355) {\n"
    "\t\tdev_err(&client->dev, \"sensor ID error, 0x%x\\n\", id);\n"
    "\t\treturn -ENODEV;\n"
    "\t}\n"
    "\n"
    "\tdev_info(&client->dev, \"detect gc2235/gc2355 success id=0x%x\\n\", id);"
)
if "id != 0x2355" in t:
    print(f"already patched detect: {p}")
elif old not in t:
    raise SystemExit(f"detect() patch anchor not found in {p}")
else:
    p.write_text(t.replace(old, new, 1))
    print(f"patched detect: {p}")
acpi = [l for l in p.read_text().splitlines() if "GCTI" in l or "INT33F8" in l or "INT2355" in l]
print("ACPI:", acpi)
PY
}

for GC in \
  atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c \
  atomisp/6.11/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c \
  atomisp/6.10/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c
do
  patch_gc2235 "$GC"
done

echo "=== setup DKMS tree ==="
VER=1.0.3-linx
SRC=/usr/src/atomisp-6.10-${VER}
rm -rf "$SRC"
mkdir -p "$SRC"
cp -a atomisp "$SRC/"
cp -a Makefile Kbuild-CFLAGS-*.mk Symbols-*.mk "$SRC/"
cp -a debian/dkms-6.10.conf "$SRC/dkms.conf"
# Allow 6.12.x (stock MAX="6.12" can exclude 6.12.96 depending on dkms)
sed -i 's/BUILD_EXCLUSIVE_KERNEL_MAX="6.12"/BUILD_EXCLUSIVE_KERNEL_MAX="6.12.99"/' "$SRC/dkms.conf"
# Stamp our package version
sed -i "s/^PACKAGE_VERSION=.*/PACKAGE_VERSION=\"${VER}\"/" "$SRC/dkms.conf"
grep -E 'PACKAGE_|BUILD_EXCLUSIVE' "$SRC/dkms.conf"

dkms remove atomisp-6.10/${VER} --all 2>/dev/null || true
dkms add "$SRC"
echo "=== dkms build (long on Atom) ==="
dkms build -m atomisp-6.10 -v "${VER}" -k "$K"
dkms install -m atomisp-6.10 -v "${VER}" -k "$K"

echo "=== modprobe policy ==="
# Allow real AtomISP; keep dummy PM from claiming 8086:22b8
# (DKMS also builds intel_atomisp2_pm — do not let it bind)
cat > /etc/modprobe.d/blacklist-atomisp.conf <<'EOF'
# Allow real AtomISP; keep dummy PM from claiming 8086:22b8
blacklist intel_atomisp2_pm
EOF
cat > /etc/modprobe.d/atomisp-load.conf <<'EOF'
softdep atomisp pre: atomisp_gmin_platform
softdep atomisp-gc2235 pre: atomisp_gmin_platform
EOF

if [[ -e /sys/bus/pci/drivers/intel_atomisp2_pm/0000:00:03.0 ]]; then
  echo -n 0000:00:03.0 > /sys/bus/pci/drivers/intel_atomisp2_pm/unbind || true
fi
rmmod intel_atomisp2_pm 2>/dev/null || true

echo "=== load modules ==="
depmod -a
modprobe atomisp_gmin_platform || true
modprobe atomisp || true
modprobe atomisp-gc2235 || true
modprobe atomisp-gc0310 || true
sleep 3
lsmod | grep -iE 'atomisp|gc2235|gc0310' || true
lspci -nnk -s 00:03.0
ls -la /dev/video* /dev/media* 2>&1 || true
dmesg | grep -iE 'atomisp|gc2235|gc2355|GCTI|shisp|css|firmware|22b8' | tail -n 100
echo OK_BUILD
