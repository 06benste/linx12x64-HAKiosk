#!/bin/bash
set -euxo pipefail
mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug
echo '=== pmc clocks ==='
grep -E 'pmc_plt_clk_' /sys/kernel/debug/clk/clk_summary | head -n 30 || true
echo '=== shisp strings ==='
xzcat /lib/modules/"$(uname -r)"/updates/dkms/atomisp.ko.xz | strings | grep -i shisp | head -n 20
echo DONE
