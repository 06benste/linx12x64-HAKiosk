#!/usr/bin/env python3
"""Set matching Bayer bus format + order (SBGGR + bggr)."""
from pathlib import Path
import re

SRC = Path("/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp")
C = SRC / "i2c/atomisp-gc2235.c"

c = C.read_text()
# Normalize all 10-bit bayer bus formats to SBGGR
c = re.sub(
    r"MEDIA_BUS_FMT_S(GRBG|RGGB|BGGR|GBRG)10_1X10",
    "MEDIA_BUS_FMT_SBGGR10_1X10",
    c,
)
# Normalize platform order to bggr
c = re.sub(
    r"atomisp_bayer_order_(grbg|rggb|bggr|gbrg)",
    "atomisp_bayer_order_bggr",
    c,
)
C.write_text(c)
print("set SBGGR10 + atomisp_bayer_order_bggr (matched)")
print("bus", "SBGGR" if "MEDIA_BUS_FMT_SBGGR10_1X10" in c else "?")
print("order counts", {k: c.count(k) for k in [
    "atomisp_bayer_order_bggr", "MEDIA_BUS_FMT_SBGGR10_1X10", "MEDIA_BUS_FMT_SGRBG10_1X10"]})
