#!/usr/bin/env python3
"""Patch atomisp_gmin_platform.c so clk4 cameras get CSI port 1 (Linx ACPI bug)."""
from pathlib import Path
import re

p = Path(
    "/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c"
)
t = p.read_text()
if "LINX_CSI_PORT_FIX" in t:
    print("already patched")
    raise SystemExit(0)

# Show context around CsiPort
for m in re.finditer(r".{0,80}CsiPort.{0,80}", t):
    print("CTX:", m.group(0).replace("\n", " "))

old = None
for cand in [
    'gs->csi_port = gmin_get_var_int(dev, false, "CsiPort", 0);',
    "gs->csi_port = gmin_get_var_int(dev, false, \"CsiPort\", 0);",
]:
    if cand in t:
        old = cand
        break
if old is None:
    m = re.search(r"gs->csi_port\s*=\s*gmin_get_var_int\([^;]+;", t)
    if not m:
        raise SystemExit("csi_port line not found")
    old = m.group(0)

new = r'''/* LINX_CSI_PORT_FIX */
	gs->csi_port = gmin_get_var_int(dev, false, "CsiPort", 0);
	/*
	 * Linx ACPI reports CsiPort=0 for both GC2355 cams. On CHT,
	 * pmc_plt_clk_4 belongs with CSI port 1 (rear), clk_2 with port 0.
	 */
	if (gs->pmc_clk) {
		const char *cn = __clk_get_name(gs->pmc_clk);
		if (cn && strstr(cn, "pmc_plt_clk_4") && gs->csi_port == 0) {
			dev_info(dev, "LINX_CSI_PORT_FIX: forcing csi_port 1 for %s\n", cn);
			gs->csi_port = 1;
		}
	}'''

# pmc_clk may not be set yet at this point in the function — check order
# Safer: use clock_num variable if present later. Do a simpler post-assign fix
# after clock is known.

# Look for "Will use CLK" or clock assignment end
print("OLD:", old)

# Prefer patching after pdata is filled — search for camera pdata print
anchor = 'dev_info(dev, "camera pdata: port: %d lanes: %d'
idx = t.find('camera pdata: port:')
if idx < 0:
    # fall back to replacing csi_port assign
    t = t.replace(old, new, 1)
else:
    # Find the statement that prints camera pdata and insert fix before it
    # Actually patch after csi_lanes assigned and after pmc clock retrieved
    pass

# Read more carefully via markers
open("/tmp/gmin_snip.txt", "w").write("\n".join(
    f"{i+1}:{l}" for i, l in enumerate(t.splitlines())
    if "csi_port" in l or "CsiPort" in l or "pmc_clk" in l or "CamClk" in l or "clock_num" in l
))
print(open("/tmp/gmin_snip.txt").read())
