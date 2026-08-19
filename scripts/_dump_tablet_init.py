#!/usr/bin/env python3
"""Dump current gc2235.h init/MIPI sections + compare key PLL regs."""
from pathlib import Path

p = Path(
    "/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h"
)
t = p.read_text()
# print from init through end of first resolution table header
i = t.find("gc2235_init_settings")
j = t.find("gc2235_res_preview")
print(t[i:j] if i >= 0 else "no init")
print("==== RES ====")
print(t[j : j + 800] if j >= 0 else "no res")
