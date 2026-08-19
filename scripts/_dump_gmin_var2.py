#!/usr/bin/env python3
from pathlib import Path
import re

t = Path(
    "/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c"
).read_text()
for m in re.finditer(r"^.*(gmin_get|gmin_var|hard.?coded|efi_var).*$", t, re.M | re.I):
    line = m.group(0).strip()
    if len(line) < 120:
        print(line)

print("--- around OVTI quirk ---")
i = t.find("OVTI2680:01_CsiPort")
print(t[i - 300 : i + 500])

print("--- gmin_get_config ---")
for name in ["gmin_get_config_var", "gmin_get_var_int", "gmin_get_hardcoded_var", "dmi_vars"]:
    i = t.find(name)
    print(name, "at", i)
