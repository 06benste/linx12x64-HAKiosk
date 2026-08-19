#!/usr/bin/env python3
"""Patch gmin CsiPort-by-clock + GC2355 2-lane option; rebuild; test both cams."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
HERE = pathlib.Path(__file__).resolve().parent

GMIN_PATCH = r'''
from pathlib import Path
p = Path("/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c")
t = p.read_text()
# Force CsiPort from pmc clock when ACPI lies (both cams report port 0 on Linx)
old = 'gs->csi_port = gmin_get_var_int(dev, false, "CsiPort", 0);'
if "LINX_CSI_PORT_FIX" in t:
    print("gmin already patched")
else:
    if old not in t:
        # try looser match
        import re
        m = re.search(r'gs->csi_port = gmin_get_var_int\([^;]+;', t)
        if not m:
            raise SystemExit("csi_port assignment not found")
        old = m.group(0)
    new = '''/* LINX_CSI_PORT_FIX: derive port from pmc clock (CHT: clk2->0, clk4->1) */
	{
		int _clk = -1, _def = 0;
		if (adev && acpi_device_power_manageable(adev))
			_clk = atomisp_get_acpi_power(dev);
		if (_clk < 0)
			_clk = gmin_get_var_int(dev, false, "CamClk", 0);
		_def = (_clk == 4) ? 1 : 0;
		gs->csi_port = gmin_get_var_int(dev, false, "CsiPort", _def);
		if (gs->csi_port == 0 && _clk == 4)
			gs->csi_port = 1; /* override bad ACPI */
		if (gs->csi_port == 1 && _clk == 2)
			gs->csi_port = 0;
		dev_info(dev, "LINX_CSI_PORT_FIX clk=%d -> csi_port=%d\\n", _clk, gs->csi_port);
	}'''
    # The above uses adev - need to ensure adev exists in scope. Check function.
    t = t.replace(old, new, 1)
    p.write_text(t)
    print("patched gmin csi port")

# Verify atomisp_get_acpi_power exists
if "atomisp_get_acpi_power" not in p.read_text() and "LINX_CSI_PORT_FIX" in p.read_text():
    # fallback without that helper
    print("WARNING: atomisp_get_acpi_power may be missing - check build")
'''

# Fix GMIN_PATCH - nested quotes are messy. Write as separate file instead.
