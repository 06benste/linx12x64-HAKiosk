#!/usr/bin/env python3
from pathlib import Path

t = Path(
    "/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c"
).read_text()
start = t.find("static int gmin_get_var_int")
print(t[start : start + 2800])
print("====")
start = t.find("gmin_vars[]")
print(t[start : start + 400])
