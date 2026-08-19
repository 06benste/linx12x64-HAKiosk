#!/usr/bin/env python3
"""Force Linx rear GC2355 (pmc_plt_clk_4) onto CSI port 1 despite bad ACPI _DSM."""
from pathlib import Path

CANDIDATES = [
    Path("/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c"),
    Path("/usr/src/atomisp-dkms-src/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c"),
]

OLD = """\tgs->csi_port = gmin_get_var_int(dev, false, \"CsiPort\", default_val);
\tgs->csi_lanes = gmin_get_var_int(dev, false, \"CsiLanes\", 1);
"""

NEW = """\tgs->csi_port = gmin_get_var_int(dev, false, \"CsiPort\", default_val);
\tgs->csi_lanes = gmin_get_var_int(dev, false, \"CsiLanes\", 1);
\t/*
\t * LINX_CSI_PORT_FIX: Linx 12X64 ACPI _DSM reports CsiPort=0 for BOTH
\t * GC2355 sensors. On Cherry Trail the rear cam uses pmc_plt_clk_4 and
\t * must be on CSI port 1. Without this, atomisp logs
\t * \"port 0 already has a sensor attached\" and only the front cam works.
\t */
\tif (IS_ISP2401 && clock_num == 4 && gs->csi_port == 0) {
\t\tdev_info(dev, \"LINX_CSI_PORT_FIX: clk4 -> csi_port 1 (was %d)\\n\",
\t\t\t gs->csi_port);
\t\tgs->csi_port = 1;
\t}
"""


def main() -> None:
    patched = 0
    for p in CANDIDATES:
        if not p.exists():
            print("skip missing", p)
            continue
        t = p.read_text()
        if "LINX_CSI_PORT_FIX" in t:
            print("already patched", p)
            continue
        if OLD not in t:
            # tolerate different whitespace
            import re

            m = re.search(
                r'\tgs->csi_port = gmin_get_var_int\(dev, false, "CsiPort", default_val\);\n'
                r'\tgs->csi_lanes = gmin_get_var_int\(dev, false, "CsiLanes", 1\);\n',
                t,
            )
            if not m:
                print("pattern missing", p)
                continue
            t = t[: m.start()] + NEW + t[m.end() :]
        else:
            t = t.replace(OLD, NEW, 1)
        p.write_text(t)
        print("patched", p)
        patched += 1
    if not patched:
        # still ok if already present
        if any("LINX_CSI_PORT_FIX" in p.read_text() for p in CANDIDATES if p.exists()):
            print("ok already present somewhere")
            return
        raise SystemExit("no files patched")


if __name__ == "__main__":
    main()
