#!/usr/bin/env bash
# Install the Linx 12X64 front camera: AtomISP DKMS driver (GC2355 sensor,
# patched from the upstream GC2235 driver) + the MJPEG stream service.
#
# This builds an out-of-tree kernel module and needs network access (clones
# a GitHub repo, downloads ISP firmware). The DKMS build logic below is
# carried over verbatim from what was actually tested working on this
# hardware — the GC2235->GC2355 chip-ID patch in particular came out of real
# iteration, not documentation, so don't "clean it up" without re-testing on
# real hardware.
set -euxo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_ROOT="/opt/ha-kiosk"
KIOSK_USER="${KIOSK_USER:-kioskuser}"
export DEBIAN_FRONTEND=noninteractive
K=$(uname -r)

echo "=== install build deps for $K ==="
apt-get update -qq
apt-get install -y -qq \
  build-essential dkms git curl ca-certificates v4l-utils ffmpeg python3-pil i2c-tools \
  "linux-headers-${K}" || apt-get install -y -qq linux-headers-amd64

echo "=== ISP firmware ==="
# The driver requests this from /lib/firmware/intel/ipu/ specifically (see
# "firmware: failed to load intel/ipu/shisp_2401a0_v21.bin" in dmesg if
# it's missing from there) — a flat /lib/firmware/shisp_2401a0_v21.bin is
# not enough on its own, confirmed on real hardware.
mkdir -p /lib/firmware/intel/ipu
if [[ ! -f /lib/firmware/intel/ipu/shisp_2401a0_v21.bin ]]; then
  curl -fsSL -o /lib/firmware/intel/ipu/shisp_2401a0_v21.bin \
    'https://github.com/intel-aero/meta-intel-aero-base/raw/master/recipes-kernel/linux/linux-yocto/shisp_2401a0_v21.bin' \
    || curl -fsSL -o /lib/firmware/intel/ipu/shisp_2401a0_v21.bin \
    'https://raw.githubusercontent.com/intel-aero/meta-intel-aero-base/master/recipes-kernel/linux/linux-yocto/shisp_2401a0_v21.bin'
fi
# Keep the flat path around too — harmless, and matches what some earlier
# manual recoveries on this hardware expected to find.
ln -sfn /lib/firmware/intel/ipu/shisp_2401a0_v21.bin /lib/firmware/shisp_2401a0_v21.bin
ls -la /lib/firmware/intel/ipu/shisp_2401a0_v21.bin /lib/firmware/intel/irci* 2>/dev/null || true

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

# --- GC2355 register/streaming patches ---
# The chip-ID patch above is only enough to get the sensor *recognized* — it
# still doesn't stream. Without the patches below, the driver loads and
# detects the sensor fine, but every capture attempt times out
# ("Warning timeout waiting for CSS to return buffers" in dmesg) because the
# GC2235 driver's stock PLL/MIPI-clock/register-burst behavior doesn't
# actually match this sensor's real timing requirements. This is carried
# over verbatim from what was confirmed (via a real captured photo, not just
# "the module loaded") working on this hardware — don't simplify without
# re-testing on real hardware.
GC_H="$SRC/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h"
GC_C="$SRC/atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c"
GC_H_PRISTINE="/usr/src/atomisp-dkms-src/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h"

echo "=== GC2355 register table (19.2MHz MCLK, 1600x1200, single-mode) ==="
python3 - "$GC_H_PRISTINE" "$GC_H" <<'PY'
from pathlib import Path
import re
import sys

src_backup = Path(sys.argv[1])
p = Path(sys.argv[2])
# Regenerate from the pristine clone each time so this stays idempotent on
# re-runs of this script instead of double-patching an already-patched file.
t = src_backup.read_text() if src_backup.exists() else p.read_text()

new_stream_on = """static struct gc2235_reg const gc2235_stream_on[] = {
	{ GC2235_8BIT, 0xfe, 0x03}, /* switch to P3 */
	{ GC2235_8BIT, 0x10, 0x94}, /* GC2355 1-lane RAW10 stream on */
	{ GC2235_8BIT, 0xfe, 0x00}, /* switch to P0 */
	{ GC2235_TOK_TERM, 0, 0 }
};"""

new_stream_off = """static struct gc2235_reg const gc2235_stream_off[] = {
	{ GC2235_8BIT, 0xfe, 0x03}, /* switch to P3 */
	{ GC2235_8BIT, 0x10, 0x00}, /* GC2355 stream off */
	{ GC2235_8BIT, 0xfe, 0x00}, /* switch to P0 */
	{ GC2235_TOK_TERM, 0, 0 }
};"""

# GC2355 analog/MIPI with PLL tuned for 19.2MHz (CHT pmc_plt_clk):
# Rockchip uses f8=0x06 @ 24MHz; scale ~1.25x -> f8=0x08.
# Keep f7/f9 close to Rockchip GC2355 values.
new_init = """static struct gc2235_reg const gc2235_init_settings[] = {
	/* GC2355 @ 19.2MHz MCLK (Cherry Trail) */
	{ GC2235_8BIT, 0xfe, 0x80 },
	{ GC2235_8BIT, 0xfe, 0x80 },
	{ GC2235_8BIT, 0xfe, 0x80 },
	{ GC2235_8BIT, 0xf2, 0x00 },
	{ GC2235_8BIT, 0xf6, 0x00 },
	{ GC2235_8BIT, 0xfc, 0x06 },
	{ GC2235_8BIT, 0xf7, 0x19 },
	{ GC2235_8BIT, 0xf8, 0x08 }, /* was 0x06 @24MHz; 19.2MHz scaled */
	{ GC2235_8BIT, 0xf9, 0x0e },
	{ GC2235_8BIT, 0xfa, 0x00 },
	{ GC2235_8BIT, 0xfe, 0x00 },
	/* Analog & cisctl — window 1616x1216; longer indoor exposure */
	{ GC2235_8BIT, 0x03, 0x06 },
	{ GC2235_8BIT, 0x04, 0x40 },
	{ GC2235_8BIT, 0x05, 0x01 },
	{ GC2235_8BIT, 0x06, 0x22 },
	{ GC2235_8BIT, 0x07, 0x00 },
	{ GC2235_8BIT, 0x08, 0x80 }, /* extra VBI for longer max exposure */
	{ GC2235_8BIT, 0x0a, 0x00 },
	{ GC2235_8BIT, 0x0c, 0x04 },
	{ GC2235_8BIT, 0x0d, 0x04 },
	{ GC2235_8BIT, 0x0e, 0xc0 },
	{ GC2235_8BIT, 0x0f, 0x06 },
	{ GC2235_8BIT, 0x10, 0x50 },
	{ GC2235_8BIT, 0x17, 0x14 },
	{ GC2235_8BIT, 0x19, 0x0b },
	{ GC2235_8BIT, 0x1b, 0x49 },
	{ GC2235_8BIT, 0x1c, 0x12 },
	{ GC2235_8BIT, 0x1d, 0x10 },
	{ GC2235_8BIT, 0x1e, 0xbc },
	{ GC2235_8BIT, 0x1f, 0xc8 },
	{ GC2235_8BIT, 0x20, 0x71 },
	{ GC2235_8BIT, 0x21, 0x20 },
	{ GC2235_8BIT, 0x22, 0xa0 },
	{ GC2235_8BIT, 0x23, 0x51 },
	{ GC2235_8BIT, 0x24, 0x19 },
	{ GC2235_8BIT, 0x27, 0x20 },
	{ GC2235_8BIT, 0x28, 0x00 },
	{ GC2235_8BIT, 0x2b, 0x81 },
	{ GC2235_8BIT, 0x2c, 0x38 },
	{ GC2235_8BIT, 0x2e, 0x16 },
	{ GC2235_8BIT, 0x2f, 0x14 },
	{ GC2235_8BIT, 0x30, 0x00 },
	{ GC2235_8BIT, 0x31, 0x01 },
	{ GC2235_8BIT, 0x32, 0x02 },
	{ GC2235_8BIT, 0x33, 0x03 },
	{ GC2235_8BIT, 0x34, 0x07 },
	{ GC2235_8BIT, 0x35, 0x0b },
	{ GC2235_8BIT, 0x36, 0x0f },
	/* Gain — stock Linux path left analog gain at 0 (near-black indoors) */
	{ GC2235_8BIT, 0xb0, 0x55 },
	{ GC2235_8BIT, 0xb1, 0x03 },
	{ GC2235_8BIT, 0xb2, 0x40 },
	{ GC2235_8BIT, 0xb3, 0x40 },
	{ GC2235_8BIT, 0xb4, 0x40 },
	{ GC2235_8BIT, 0xb5, 0x40 },
	{ GC2235_8BIT, 0xb6, 0x03 },
	/* Crop 1600x1200 */
	{ GC2235_8BIT, 0x90, 0x01 },
	{ GC2235_8BIT, 0x92, 0x02 },
	{ GC2235_8BIT, 0x95, 0x04 },
	{ GC2235_8BIT, 0x96, 0xb0 },
	{ GC2235_8BIT, 0x97, 0x06 },
	{ GC2235_8BIT, 0x98, 0x40 },
	/* BLK */
	{ GC2235_8BIT, 0x18, 0x02 },
	{ GC2235_8BIT, 0x1a, 0x01 },
	{ GC2235_8BIT, 0x40, 0x42 },
	{ GC2235_8BIT, 0x41, 0x00 },
	{ GC2235_8BIT, 0x44, 0x00 },
	{ GC2235_8BIT, 0x45, 0x00 },
	{ GC2235_8BIT, 0x46, 0x00 },
	{ GC2235_8BIT, 0x47, 0x00 },
	{ GC2235_8BIT, 0x48, 0x00 },
	{ GC2235_8BIT, 0x49, 0x00 },
	{ GC2235_8BIT, 0x4a, 0x00 },
	{ GC2235_8BIT, 0x4b, 0x00 },
	{ GC2235_8BIT, 0x4e, 0x3c },
	{ GC2235_8BIT, 0x4f, 0x00 },
	{ GC2235_8BIT, 0x5e, 0x00 },
	{ GC2235_8BIT, 0x66, 0x20 },
	{ GC2235_8BIT, 0x6a, 0x02 },
	{ GC2235_8BIT, 0x6b, 0x02 },
	{ GC2235_8BIT, 0x6c, 0x00 },
	{ GC2235_8BIT, 0x6d, 0x00 },
	{ GC2235_8BIT, 0x6e, 0x00 },
	{ GC2235_8BIT, 0x6f, 0x00 },
	{ GC2235_8BIT, 0x70, 0x02 },
	{ GC2235_8BIT, 0x71, 0x02 },
	{ GC2235_8BIT, 0x87, 0x03 },
	{ GC2235_8BIT, 0xe0, 0xe7 },
	{ GC2235_8BIT, 0xe3, 0xc0 },
	/* MIPI 1-lane RAW10 (front CAM7 / CsiLanes=1) */
	{ GC2235_8BIT, 0xfe, 0x03 },
	{ GC2235_8BIT, 0x01, 0x83 },
	{ GC2235_8BIT, 0x02, 0x00 },
	{ GC2235_8BIT, 0x03, 0x90 },
	{ GC2235_8BIT, 0x04, 0x01 },
	{ GC2235_8BIT, 0x05, 0x00 },
	{ GC2235_8BIT, 0x06, 0xa2 },
	{ GC2235_8BIT, 0x10, 0x00 },
	{ GC2235_8BIT, 0x11, 0x2b },
	{ GC2235_8BIT, 0x12, 0xd0 }, /* (1600*10/8)=2000=0x07d0 */
	{ GC2235_8BIT, 0x13, 0x07 },
	{ GC2235_8BIT, 0x15, 0x60 },
	{ GC2235_8BIT, 0x21, 0x10 },
	{ GC2235_8BIT, 0x22, 0x05 },
	{ GC2235_8BIT, 0x23, 0x30 },
	{ GC2235_8BIT, 0x24, 0x02 },
	{ GC2235_8BIT, 0x25, 0x15 },
	{ GC2235_8BIT, 0x26, 0x08 },
	{ GC2235_8BIT, 0x27, 0x06 },
	{ GC2235_8BIT, 0x29, 0x06 },
	{ GC2235_8BIT, 0x2a, 0x0a },
	{ GC2235_8BIT, 0x2b, 0x08 },
	{ GC2235_8BIT, 0x40, 0x00 },
	{ GC2235_8BIT, 0x41, 0x00 },
	{ GC2235_8BIT, 0x42, 0x40 },
	{ GC2235_8BIT, 0x43, 0x06 },
	{ GC2235_8BIT, 0xfe, 0x00 },
	{ GC2235_TOK_TERM, 0, 0 }
};"""

t = re.sub(
    r"static struct gc2235_reg const gc2235_stream_on\[\] = \{.*?\};",
    new_stream_on, t, count=1, flags=re.S,
)
t = re.sub(
    r"static struct gc2235_reg const gc2235_stream_off\[\] = \{.*?\};",
    new_stream_off, t, count=1, flags=re.S,
)
t = re.sub(
    r"static struct gc2235_reg const gc2235_init_settings\[\] = \{.*?\};",
    new_init, t, count=1, flags=re.S,
)

# Collapse preview resolutions to a single 1600x1200 entry that does NOT
# reprogram MIPI (avoids GC2235 res tables clobbering GC2355 init).
new_res_regs = """static struct gc2235_reg const gc2235_1600_900_30fps[] = {
	/* keep crop; MIPI already set in init_settings */
	{ GC2235_8BIT, 0x90, 0x01 },
	{ GC2235_8BIT, 0x92, 0x02 },
	{ GC2235_8BIT, 0x95, 0x04 },
	{ GC2235_8BIT, 0x96, 0xb0 },
	{ GC2235_8BIT, 0x97, 0x06 },
	{ GC2235_8BIT, 0x98, 0x40 },
	{ GC2235_TOK_TERM, 0, 0 }
};"""
t = re.sub(
    r"static struct gc2235_reg const gc2235_1600_900_30fps\[\] = \{.*?\};",
    new_res_regs, t, count=1, flags=re.S,
)

new_preview = """static struct gc2235_resolution gc2235_res_preview[] = {
	{
		.desc = "gc2355_1600_1200_30fps",
		.width = 1600,
		.height = 1200,
		.pix_clk_freq = 30,
		.fps = 30,
		.used = 0,
		.pixels_per_line = 2252,
		.lines_per_frame = 1241,
		.skip_frames = 3,
		.regs = gc2235_1600_900_30fps,
	},
};

#define N_RES_PREVIEW (ARRAY_SIZE(gc2235_res_preview))
"""
t = re.sub(
    r"static struct gc2235_resolution gc2235_res_preview\[\] = \{.*?#define N_RES_PREVIEW \(ARRAY_SIZE\(gc2235_res_preview\)\)",
    new_preview.rstrip() + "\n", t, count=1, flags=re.S,
)

p.write_text(t)
print("patched", p)
PY

echo "=== GC2355 Bayer bus format/order (must match, or the image is garbage even if frames arrive) ==="
python3 - "$GC_C" <<'PY'
from pathlib import Path
import re
import sys

C = Path(sys.argv[1])
c = C.read_text()
c = re.sub(r"MEDIA_BUS_FMT_S(GRBG|RGGB|BGGR|GBRG)10_1X10", "MEDIA_BUS_FMT_SBGGR10_1X10", c)
c = re.sub(r"atomisp_bayer_order_(grbg|rggb|bggr|gbrg)", "atomisp_bayer_order_bggr", c)
C.write_text(c)
print("set SBGGR10 + atomisp_bayer_order_bggr (matched)")
PY

echo "=== GC2355 streaming fixes: continuous MIPI clock, single-register I2C writes ==="
# The single biggest lever for the CSS-timeout symptom: the stock GC2235
# driver bursts consecutive register writes in one I2C transaction and uses
# a gapped (non-continuous) MIPI HS clock lane — both wrong for this sensor.
python3 - "$GC_H" "$GC_C" <<'PY'
from pathlib import Path
import re
import sys

H = Path(sys.argv[1])
C = Path(sys.argv[2])

h = H.read_text()

new_stream_on = """static struct gc2235_reg const gc2235_stream_on[] = {
	{ GC2235_8BIT, 0xfe, 0x03}, /* switch to P3 */
	{ GC2235_8BIT, 0x10, 0x90}, /* GC2355 MODE_STREAMING */
	{ GC2235_8BIT, 0xfe, 0x00}, /* switch to P0 */
	{ GC2235_TOK_TERM, 0, 0 }
};"""
new_stream_off = """static struct gc2235_reg const gc2235_stream_off[] = {
	{ GC2235_8BIT, 0xfe, 0x03}, /* switch to P3 */
	{ GC2235_8BIT, 0x10, 0x00}, /* GC2355 MODE_SW_STANDBY */
	{ GC2235_8BIT, 0xfe, 0x00}, /* switch to P0 */
	{ GC2235_TOK_TERM, 0, 0 }
};"""
h = re.sub(r"static struct gc2235_reg const gc2235_stream_on\[\] = \{.*?\};", new_stream_on, h, count=1, flags=re.S)
h = re.sub(r"static struct gc2235_reg const gc2235_stream_off\[\] = \{.*?\};", new_stream_off, h, count=1, flags=re.S)

# Force GC2355 PLL (not GC2235's stock f7/f8/f9)
h2, n = re.subn(
    r"\{ GC2235_8BIT, 0xf7, 0x[0-9a-fA-F]+ \},.*?\n"
    r"\t\{ GC2235_8BIT, 0xf8, 0x[0-9a-fA-F]+ \},.*?\n"
    r"\t\{ GC2235_8BIT, 0xf9, 0x[0-9a-fA-F]+ \},.*?\n",
    "{ GC2235_8BIT, 0xf7, 0x19 }, /* GC2355 clk_double */\n"
    "\t{ GC2235_8BIT, 0xf8, 0x08 }, /* PLL mode2 scaled 24->19.2MHz */\n"
    "\t{ GC2235_8BIT, 0xf9, 0x0e }, /* pll enable */\n",
    h, count=1, flags=re.S,
)
if n != 1:
    raise SystemExit(f"PLL replace failed n={n}")
h = h2

# Continuous HS clock lane (0x15 = 0x62, was 0x60)
h2, n = re.subn(
    r"\{ GC2235_8BIT, 0x15, 0x60\s*\},?",
    "{ GC2235_8BIT, 0x15, 0x62 }, /* continuous HS clk lane */",
    h, count=1,
)
if n != 1:
    raise SystemExit(f"0x15 replace failed n={n}")
h = h2

H.write_text(h)
print("patched gc2235.h: stream/PLL/0x15")

c = C.read_text()

if "LINX_SINGLE_I2C_WRITES" not in c:
    old = """static int __gc2235_write_reg_is_consecutive(struct i2c_client *client,
					     struct gc2235_write_ctrl *ctrl,
					     const struct gc2235_reg *next)
{
	if (ctrl->index == 0)
		return 1;

	return ctrl->buffer.addr + ctrl->index == next->reg;
}"""
    new = """static int __gc2235_write_reg_is_consecutive(struct i2c_client *client,
					     struct gc2235_write_ctrl *ctrl,
					     const struct gc2235_reg *next)
{
	/* LINX_SINGLE_I2C_WRITES: GC2355 is happier with 1-reg transactions
	 * (Rockchip driver never bursts). Disable consecutive buffering.
	 */
	(void)client;
	(void)ctrl;
	(void)next;
	return 0;
}"""
    if old not in c:
        raise SystemExit("consecutive helper not found")
    c = c.replace(old, new, 1)
    print("patched single I2C writes")

if "LINX_STREAM_READBACK" not in c:
    old = """static int gc2235_s_stream(struct v4l2_subdev *sd, int enable)
{
	struct gc2235_device *dev = to_gc2235_sensor(sd);
	struct i2c_client *client = v4l2_get_subdevdata(sd);
	int ret;

	mutex_lock(&dev->input_lock);

	if (enable)
		ret = gc2235_write_reg_array(client, gc2235_stream_on);
	else
		ret = gc2235_write_reg_array(client, gc2235_stream_off);

	mutex_unlock(&dev->input_lock);
	return ret;
}"""
    new = """static int gc2235_s_stream(struct v4l2_subdev *sd, int enable)
{
	struct gc2235_device *dev = to_gc2235_sensor(sd);
	struct i2c_client *client = v4l2_get_subdevdata(sd);
	int ret;
	u16 v = 0;

	mutex_lock(&dev->input_lock);

	if (enable)
		ret = gc2235_write_reg_array(client, gc2235_stream_on);
	else
		ret = gc2235_write_reg_array(client, gc2235_stream_off);

	/* LINX_STREAM_READBACK */
	if (!ret && enable) {
		gc2235_write_reg(client, GC2235_8BIT, 0xfe, 0x03);
		gc2235_read_reg(client, GC2235_8BIT, 0x10, &v);
		dev_info(&client->dev,
			 "LINX_STREAM_READBACK p3.0x10=0x%02x (want 0x90)\\n", v);
		gc2235_write_reg(client, GC2235_8BIT, 0xfe, 0x00);
		gc2235_read_reg(client, GC2235_8BIT, 0xf7, &v);
		dev_info(&client->dev, "LINX_STREAM_READBACK p0.f7=0x%02x\\n", v);
		gc2235_read_reg(client, GC2235_8BIT, 0xf8, &v);
		dev_info(&client->dev, "LINX_STREAM_READBACK p0.f8=0x%02x\\n", v);
		gc2235_read_reg(client, GC2235_8BIT, 0xf9, &v);
		dev_info(&client->dev, "LINX_STREAM_READBACK p0.f9=0x%02x\\n", v);
	} else {
		dev_info(&client->dev,
			 "LINX_STREAM_READBACK enable=%d ret=%d\\n", enable, ret);
	}

	mutex_unlock(&dev->input_lock);
	return ret;
}"""
    if old not in c:
        raise SystemExit("s_stream not found for readback patch")
    c = c.replace(old, new, 1)
    print("patched s_stream readback")

C.write_text(c)
print("OK")
PY

echo "=== rear camera CSI port/lane ACPI quirk ==="
# The Linx 12X64's ACPI _DSM reports CsiPort=0 for BOTH front and rear
# GC2355 sensors (front is genuinely port 0; rear is actually on CSI port 1
# via pmc_plt_clk_4, but the firmware never says so). Without this, atomisp
# logs "port 0 already has a sensor attached" and only the front camera
# actually registers on the ISP side — the rear sensor still responds to
# i2c (detect succeeds, exposure/gain writes work) but its video data path
# never binds, so /dev/video0 input 1 silently reads the front sensor
# instead of failing outright. Confirmed on real hardware: this is why
# "rear" and "front" captures looked identical before this patch.
# ACPI also over-reports CsiLanes=2 for the rear sensor; the wiring
# actually matches the front's 1-lane setup.
GMIN_C="$SRC/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c"
python3 - "$GMIN_C" <<'PY'
from pathlib import Path
import re
import sys

p = Path(sys.argv[1])
t = p.read_text()

port_fix = """\tif (IS_ISP2401 && clock_num == 4 && gs->csi_port == 0) {
\t\tdev_info(dev, "LINX_CSI_PORT_FIX: clk4 -> csi_port 1 (was %d)\\n",
\t\t\t gs->csi_port);
\t\tgs->csi_port = 1;
\t}
"""
lanes_fix = """\t/* Linx rear GC2355: ACPI CsiLanes=2 but hardware matches front (1-lane). */
\tif (IS_ISP2401 && clock_num == 4 && gs->csi_lanes > 1) {
\t\tdev_info(dev, "LINX_CSI_LANES_FIX: clk4 -> csi_lanes 1 (was %d)\\n",
\t\t\t gs->csi_lanes);
\t\tgs->csi_lanes = 1;
\t}
"""

if "LINX_CSI_LANES_FIX" in t:
    print("already patched (port+lanes)")
else:
    if "LINX_CSI_PORT_FIX" not in t:
        anchor = re.search(
            r'\tgs->csi_port = gmin_get_var_int\(dev, false, "CsiPort", default_val\);\n'
            r'\tgs->csi_lanes = gmin_get_var_int\(dev, false, "CsiLanes", 1\);\n',
            t,
        )
        if not anchor:
            raise SystemExit("CsiPort/CsiLanes assignment anchor not found in atomisp_gmin_platform.c")
        t = t[: anchor.end()] + port_fix + t[anchor.end() :]
        print("patched port fix")
    anchor2 = t.find(port_fix)
    if anchor2 == -1:
        raise SystemExit("port_fix block not found after insertion (formatting mismatch)")
    insert_at = anchor2 + len(port_fix)
    t = t[:insert_at] + lanes_fix + t[insert_at:]
    print("patched lanes fix")

p.write_text(t)
print("OK")
PY

# Allow 6.12.x (stock MAX="6.12" can exclude 6.12.96 depending on dkms)
# Match any 6.12.x — a fixed ceiling like "6.12.99" silently stops building
# the moment Debian ships a kernel point-release past it (confirmed on real
# hardware: kernel 6.12.101+deb13-amd64 already exceeds that, so `dkms build`
# no-ops and the script aborts under set -e before ever installing the
# camera-stream service — no error, just silently incomplete). The upstream
# source always ships some literal ceiling here; override whatever it is.
sed -i -E 's/BUILD_EXCLUSIVE_KERNEL_MAX="6\.12[^"]*"/BUILD_EXCLUSIVE_KERNEL_MAX="6.12.9999"/' "$SRC/dkms.conf"
# Stamp our package version
sed -i "s/^PACKAGE_VERSION=.*/PACKAGE_VERSION=\"${VER}\"/" "$SRC/dkms.conf"
grep -E 'PACKAGE_|BUILD_EXCLUSIVE' "$SRC/dkms.conf"

dkms remove atomisp-6.10/${VER} --all 2>/dev/null || true
dkms add "$SRC"
echo "=== dkms build (long on Atom) ==="
dkms build -m atomisp-6.10 -v "${VER}" -k "$K"
dkms install -m atomisp-6.10 -v "${VER}" -k "$K"

# dkms build/install can both exit 0 while having silently done nothing (e.g.
# a BUILD_EXCLUSIVE_KERNEL mismatch just prints a Warning and no-ops) — don't
# trust the exit code alone. Confirm the module actually reached "installed".
if ! dkms status -m atomisp-6.10 -v "${VER}" -k "$K" | grep -q installed; then
  echo "ERROR: atomisp-6.10/${VER} did not reach 'installed' status for kernel $K." >&2
  dkms status -m atomisp-6.10 -v "${VER}" >&2 || true
  exit 1
fi

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

echo "=== install module-load service ==="
install -d -m 755 "$INSTALL_ROOT/scripts"
install -m 755 "$ROOT/scripts/load-atomisp.sh" "$INSTALL_ROOT/scripts/load-atomisp.sh"
install -m 644 "$ROOT/scripts/ha-kiosk-atomisp.service" /etc/systemd/system/ha-kiosk-atomisp.service

echo "=== install camera stream service ==="
install -d -m 755 "$INSTALL_ROOT/config" "$INSTALL_ROOT/scripts/static" "$INSTALL_ROOT/bin"
install -m 644 "$ROOT/config/camera_preview.json" "$INSTALL_ROOT/config/camera_preview.json"
install -m 755 "$ROOT/scripts/camera-stream-server.py" "$INSTALL_ROOT/scripts/camera-stream-server.py"
install -m 644 "$ROOT/scripts/camera_preview.py" "$INSTALL_ROOT/scripts/camera_preview.py"
install -m 755 "$ROOT/scripts/capture-tablet-cam.py" "$INSTALL_ROOT/scripts/capture-tablet-cam.py"
install -m 644 "$ROOT/scripts/gc2355_hw_exposure.py" "$INSTALL_ROOT/scripts/gc2355_hw_exposure.py"
install -m 644 "$ROOT/scripts/static/cam-tuner.html" "$INSTALL_ROOT/scripts/static/cam-tuner.html"
install -m 755 "$ROOT/scripts/ha-cam-tuner" "$INSTALL_ROOT/bin/ha-cam-tuner"
install -m 755 "$ROOT/scripts/ha-cam-tuner" "$INSTALL_ROOT/scripts/ha-cam-tuner"
ln -sfn "$INSTALL_ROOT/bin/ha-cam-tuner" /usr/local/bin/ha-cam-tuner
install -m 644 "$ROOT/scripts/ha-kiosk-camera-stream.service" /etc/systemd/system/ha-kiosk-camera-stream.service

chown -R "$KIOSK_USER:$KIOSK_USER" "$INSTALL_ROOT" 2>/dev/null || true

modprobe i2c-dev || true
systemctl daemon-reload
systemctl enable --now ha-kiosk-atomisp.service
systemctl enable --now ha-kiosk-camera-stream.service

echo
echo "Camera installed. A reboot is recommended so the module load order is"
echo "applied cleanly from boot: sudo reboot"
echo "After reboot, check: systemctl status ha-kiosk-camera-stream.service"
echo "Live stream: http://<tablet-ip>:17824/stream.mjpg"
echo "Tuning UI:   drawer's 'Tablet Setup' button -> Cameras tab (or directly at http://<tablet-ip>:17824/tuner)"
