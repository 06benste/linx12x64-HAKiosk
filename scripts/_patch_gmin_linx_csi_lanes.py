#!/usr/bin/env python3
"""Force Linx rear GC2355 to 1 CSI lane (ACPI claims 2; front works at 1)."""
from pathlib import Path

CANDIDATES = [
    Path("/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c"),
    Path("/usr/src/atomisp-dkms-src/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c"),
]

NEEDLE = """\tif (IS_ISP2401 && clock_num == 4 && gs->csi_port == 0) {
\t\tdev_info(dev, \"LINX_CSI_PORT_FIX: clk4 -> csi_port 1 (was %d)\\n\",
\t\t\t gs->csi_port);
\t\tgs->csi_port = 1;
\t}
"""

INSERT = """\tif (IS_ISP2401 && clock_num == 4 && gs->csi_port == 0) {
\t\tdev_info(dev, \"LINX_CSI_PORT_FIX: clk4 -> csi_port 1 (was %d)\\n\",
\t\t\t gs->csi_port);
\t\tgs->csi_port = 1;
\t}
\t/* Linx rear GC2355: ACPI CsiLanes=2 but hardware matches front (1-lane). */
\tif (IS_ISP2401 && clock_num == 4 && gs->csi_lanes > 1) {
\t\tdev_info(dev, \"LINX_CSI_LANES_FIX: clk4 -> csi_lanes 1 (was %d)\\n\",
\t\t\t gs->csi_lanes);
\t\tgs->csi_lanes = 1;
\t}
"""


def main() -> None:
    for p in CANDIDATES:
        if not p.exists():
            print("skip", p)
            continue
        t = p.read_text()
        if "LINX_CSI_LANES_FIX" in t:
            print("already", p)
            continue
        if NEEDLE not in t:
            print("needle missing", p)
            continue
        p.write_text(t.replace(NEEDLE, INSERT, 1))
        print("patched", p)


if __name__ == "__main__":
    main()
