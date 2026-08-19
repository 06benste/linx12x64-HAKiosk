#!/usr/bin/env python3
"""
Patch installed atomisp-gc2235 so set_exposure also programs analog gain (0xb6),
then rebuild DKMS. Safer than continuous userspace i2c forcing.
"""
from __future__ import annotations

from pathlib import Path

CANDIDATES = [
    Path("/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c"),
    Path("/usr/src/atomisp-dkms-src/atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c"),
]

OLD = """\tret = gc2235_write_reg(client, GC2235_8BIT,
\t\t\t       GC2235_GLOBAL_GAIN, (u8)gain_val);
\tret = gc2235_write_reg(client, GC2235_8BIT,
\t\t\t       GC2235_PRE_GAIN, (u8)gain_val2);

\treturn ret;
"""

NEW = """\tret = gc2235_write_reg(client, GC2235_8BIT,
\t\t\t       GC2235_GLOBAL_GAIN, (u8)gain_val);
\tret = gc2235_write_reg(client, GC2235_8BIT,
\t\t\t       GC2235_PRE_GAIN, (u8)gain_val2);
\t/* GC2355: analog gain lives at 0xb6; without it indoor frames stay crushed. */
\t{
\t\tu8 again = 0x03;
\t\tif (gain >= 0x180)
\t\t\tagain = 0x06;
\t\telse if (gain >= 0x100)
\t\t\tagain = 0x05;
\t\telse if (gain >= 0xC0)
\t\t\tagain = 0x04;
\t\telse if (gain >= 0x80)
\t\t\tagain = 0x03;
\t\telse if (gain >= 0x60)
\t\t\tagain = 0x02;
\t\telse
\t\t\tagain = 0x01;
\t\tret = gc2235_write_reg(client, GC2235_8BIT, 0xb6, again);
\t}

\treturn ret;
"""


def main() -> None:
    patched = 0
    for p in CANDIDATES:
        if not p.exists():
            print("skip missing", p)
            continue
        t = p.read_text()
        if "analog gain lives at 0xb6" in t:
            print("already patched", p)
            continue
        if OLD not in t:
            print("pattern missing", p)
            continue
        p.write_text(t.replace(OLD, NEW, 1))
        print("patched", p)
        patched += 1
    if not patched:
        raise SystemExit("no files patched")


if __name__ == "__main__":
    main()
