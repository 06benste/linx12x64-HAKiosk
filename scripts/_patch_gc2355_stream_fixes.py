#!/usr/bin/env python3
"""
Apply high-value GC2355 streaming fixes on tablet sources:
1) Force single-register I2C writes (disable consecutive burst buffering)
2) Continuous MIPI clock lane (0x15=0x62)
3) Pure GC2355 PLL scaled for 19.2MHz (f7=0x19,f8=0x08,f9=0x0e)
4) Stream on 0x90 (Rockchip MODE_STREAMING)
5) printk + readback after s_stream(1)
"""
from pathlib import Path
import re

SRC = Path("/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp")
H = SRC / "i2c/gc2235.h"
C = SRC / "i2c/atomisp-gc2235.c"

# --- header: stream + PLL + continuous clock ---
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

h = re.sub(
    r"static struct gc2235_reg const gc2235_stream_on\[\] = \{.*?\};",
    new_stream_on,
    h,
    count=1,
    flags=re.S,
)
h = re.sub(
    r"static struct gc2235_reg const gc2235_stream_off\[\] = \{.*?\};",
    new_stream_off,
    h,
    count=1,
    flags=re.S,
)

# Force GC2355 PLL (not GC2235's f7/f8/f9)
h2, n = re.subn(
    r"\{ GC2235_8BIT, 0xf7, 0x[0-9a-fA-F]+ \},.*?\n"
    r"\t\{ GC2235_8BIT, 0xf8, 0x[0-9a-fA-F]+ \},.*?\n"
    r"\t\{ GC2235_8BIT, 0xf9, 0x[0-9a-fA-F]+ \},.*?\n",
    "{ GC2235_8BIT, 0xf7, 0x19 }, /* GC2355 clk_double */\n"
    "\t{ GC2235_8BIT, 0xf8, 0x08 }, /* PLL mode2 scaled 24->19.2MHz */\n"
    "\t{ GC2235_8BIT, 0xf9, 0x0e }, /* pll enable */\n",
    h,
    count=1,
    flags=re.S,
)
if n != 1:
    raise SystemExit(f"PLL replace failed n={n}")
h = h2

# Continuous HS clock lane: 0x15 low bits = 10b
# Fix any prior botched double-comma patch first.
h2, n = re.subn(
    r"\{ GC2235_8BIT, 0x15, 0x62\s*\},\s*/\* continuous HS clk lane \*/,",
    "{ GC2235_8BIT, 0x15, 0x62 }, /* continuous HS clk lane */",
    h,
    count=1,
)
if n:
    h = h2
    print("fixed botched 0x15 comma")
elif re.search(r"\{ GC2235_8BIT, 0x15, 0x62\s*\}", h):
    print("0x15 already ok")
else:
    h2, n = re.subn(
        r"\{ GC2235_8BIT, 0x15, 0x60\s*\},?",
        "{ GC2235_8BIT, 0x15, 0x62 }, /* continuous HS clk lane */",
        h,
        count=1,
    )
    if n != 1:
        raise SystemExit(f"0x15 replace failed n={n}")
    h = h2

# Guard: never leave empty array slots
if re.search(r"clk lane \*/,", h):
    raise SystemExit("still have double-comma after 0x15 patch")

H.write_text(h)
print("patched gc2235.h: stream/PLL/0x15")

# --- C: single writes + stream readback ---
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
else:
    print("single I2C writes already present")

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
else:
    print("readback already present")

C.write_text(c)
print("OK")
