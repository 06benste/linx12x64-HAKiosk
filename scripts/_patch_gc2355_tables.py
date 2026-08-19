#!/usr/bin/env python3
"""Patch gc2235.h for GC2355 @ 19.2MHz MCLK (Cherry Trail), single 1600x1200 mode."""
from pathlib import Path

p = Path("/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h")
# Start from pristine copy if we saved one; else patch current
src_backup = Path("/usr/src/atomisp-dkms-src/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h")
if src_backup.exists():
    # Prefer pristine, then re-apply ACPI/id patches live in .c not .h
    t = src_backup.read_text()
else:
    t = p.read_text()

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

# Replace stream_on/off blocks (match either original or previously patched)
import re
t = re.sub(
    r"static struct gc2235_reg const gc2235_stream_on\[\] = \{.*?\};",
    new_stream_on,
    t,
    count=1,
    flags=re.S,
)
t = re.sub(
    r"static struct gc2235_reg const gc2235_stream_off\[\] = \{.*?\};",
    new_stream_off,
    t,
    count=1,
    flags=re.S,
)
t = re.sub(
    r"static struct gc2235_reg const gc2235_init_settings\[\] = \{.*?\};",
    new_init,
    t,
    count=1,
    flags=re.S,
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

# Replace from first res reg array used by preview through end of preview array
# Easiest: replace gc2235_res_preview definition entirely.
t = re.sub(
    r"static struct gc2235_reg const gc2235_1600_900_30fps\[\] = \{.*?\};",
    new_res_regs,
    t,
    count=1,
    flags=re.S,
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
    new_preview.rstrip() + "\n",
    t,
    count=1,
    flags=re.S,
)

# Still/video arrays still reference other regs — keep them but unused if N_RES uses preview.
# Ensure default pointer is preview (already is).

p.write_text(t)
text = p.read_text()
print("patched", p)
print("stream 0x94:", "0x10, 0x94" in text)
print("f8 0x08:", "0xf8, 0x08" in text)
print("single preview:", text.count("gc2355_1600_1200_30fps") >= 1)
print("preview entries approx:", text[text.find("gc2235_res_preview"):text.find("N_RES_PREVIEW")].count(".width"))
