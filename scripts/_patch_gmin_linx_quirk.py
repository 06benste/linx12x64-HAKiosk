#!/usr/bin/env python3
"""Add Linx GCTI2355 CsiPort quirks to atomisp_gmin_platform.c."""
from pathlib import Path

p = Path(
    "/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c"
)
t = p.read_text()
if "GCTI2355:01_CsiPort" in t:
    print("quirk already present")
    raise SystemExit(0)

needle = '\t/* _DSM contains the wrong CsiPort! */\n\t{ "OVTI2680:01_CsiPort", "0" },'
insert = (
    '\t/* _DSM contains the wrong CsiPort! */\n'
    '\t{ "OVTI2680:01_CsiPort", "0" },\n'
    '\t/* Linx 12X64: both GC2355 report CsiPort 0; rear is on pmc_plt_clk_4 */\n'
    '\t{ "GCTI2355:01_CsiPort", "1" },\n'
    '\t{ "GCTI2355:00_CsiPort", "0" },'
)
if needle not in t:
    raise SystemExit("quirk anchor not found")
p.write_text(t.replace(needle, insert, 1))
print("added GCTI2355 CsiPort quirks")
