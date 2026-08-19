#!/usr/bin/env python3
from pathlib import Path

p = Path(
    "/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c"
)
t = p.read_text()
for name in [
    "gc2235_s_stream",
    "gc2235_s_power",
    "__gc2235_s_power",
    "__gc2235_init",
    "gc2235_s_config",
]:
    i = t.find(f"static int {name}")
    if i < 0:
        i = t.find(f"static int {name}")
    print("====", name, "at", i)
    if i >= 0:
        print(t[i : i + 1200])
        print("---")

# Also check core ops registration
i = t.find("s_stream")
print("s_stream refs:")
for j, line in enumerate(t.splitlines(), 1):
    if "s_stream" in line or "s_power" in line or "core_ops" in line or "video_ops" in line:
        print(f"{j}:{line}")
