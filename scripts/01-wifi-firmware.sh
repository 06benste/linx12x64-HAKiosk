#!/usr/bin/env bash
# Install Linx 12X64 Broadcom 43455 firmware (no Windows drivers required).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/firmware/brcm"
DEST="/lib/firmware/brcm"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

if [[ ! -f "$SRC/brcmfmac43455-sdio.txt" ]]; then
  echo "Missing $SRC/brcmfmac43455-sdio.txt" >&2
  exit 1
fi

mkdir -p "$DEST"
install -m 644 "$SRC/brcmfmac43455-sdio.txt" "$DEST/brcmfmac43455-sdio.txt"

if [[ -f "$SRC/brcmfmac43455-sdio.bin" ]]; then
  install -m 644 "$SRC/brcmfmac43455-sdio.bin" "$DEST/brcmfmac43455-sdio.bin"
fi
if [[ -f "$SRC/brcmfmac43455-sdio.clm_blob" ]]; then
  install -m 644 "$SRC/brcmfmac43455-sdio.clm_blob" "$DEST/brcmfmac43455-sdio.clm_blob"
fi

# DMI-specific names the Debian installer / kernel ask for on this tablet
for kind in bin txt clm_blob; do
  src="$SRC/brcmfmac43455-sdio.LINX-LINX12X64.$kind"
  # fall back to generic file if Linx-named copy missing
  if [[ ! -f "$src" && -f "$SRC/brcmfmac43455-sdio.$kind" ]]; then
    src="$SRC/brcmfmac43455-sdio.$kind"
  fi
  if [[ -f "$src" ]]; then
    install -m 644 "$src" "$DEST/brcmfmac43455-sdio.LINX-LINX12X64.$kind"
  fi
done

# Optional Bluetooth firmware (cameras still won't work; BT audio is flaky on this SoC)
if [[ -f "$SRC/BCM4345C0_003.001.025.0110.0169.hcd" ]]; then
  install -m 644 "$SRC/BCM4345C0_003.001.025.0110.0169.hcd" \
    "$DEST/BCM4345C0.hcd"
  # Common aliases some kernels look for
  ln -sf BCM4345C0.hcd "$DEST/BCM4345C0.3.001.025.0110.0169.hcd" 2>/dev/null || true
fi

# Rotation sensor map (harmless if unused)
if [[ -f "$ROOT/firmware/61-sensor-local.hwdb" ]]; then
  install -m 644 "$ROOT/firmware/61-sensor-local.hwdb" \
    /etc/udev/hwdb.d/61-sensor-local.hwdb
  systemd-hwdb update || udevadm hwdb --update || true
fi

modprobe -r brcmfmac 2>/dev/null || true
modprobe brcmfmac

echo "Firmware installed. Waiting for interface..."
sleep 2
ip -br link || true
dmesg | grep -iE 'brcm|firmware' | tail -n 20 || true

# --- Migrate any Debian-installer-written static wlan0 config to NetworkManager ---
# If Wi-Fi was configured during the Debian installer (docs/INSTALL.md §4),
# the installer writes a static wpa-ssid/wpa-psk stanza straight into
# /etc/network/interfaces. Debian's default NetworkManager.conf has
# [ifupdown] managed=false, so NetworkManager silently ignores any interface
# ifupdown already claims — wlan0 still works (ifupdown brings it up fine),
# but nmcli-based tools (nmtui, and this project's own setup-screen Wi-Fi
# tab) see nothing at all: no scan results, "No networks found".
#
# Confirmed on real hardware, the hard way: a live, unverified cutover left
# a tablet's Wi-Fi down until a physical reboot. This version verifies the
# new NetworkManager connection actually gets an IP before touching the old
# config, and automatically rolls back if it doesn't — safe to run
# unattended as part of install.sh re-runs.
IFACES=/etc/network/interfaces
if [[ -f "$IFACES" ]] && grep -q '^iface wlan0' "$IFACES" 2>/dev/null && command -v nmcli >/dev/null; then
  echo
  echo "=== migrating wlan0 from static ifupdown config to NetworkManager ==="
  SSID="$(awk '/wpa-ssid/{print $2; exit}' "$IFACES")"
  PSK="$(awk '/wpa-psk/{print $2; exit}' "$IFACES")"
  if [[ -n "$SSID" && -n "$PSK" ]]; then
    cp -a "$IFACES" "${IFACES}.bak-nm-migrate"
    nmcli connection delete "$SSID" >/dev/null 2>&1 || true
    nmcli connection add type wifi con-name "$SSID" ifname wlan0 ssid "$SSID" \
      wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" connection.autoconnect yes >/dev/null

    # Comment out (don't delete) the ifupdown stanza so NetworkManager's
    # managed=false rule — which only excludes interfaces ifupdown still
    # claims — stops applying to wlan0.
    python3 - "$IFACES" <<'PY'
import sys
p = sys.argv[1]
t = open(p).read()
out = []
for line in t.splitlines(keepends=True):
    s = line.strip()
    if s.startswith(("allow-hotplug wlan0", "iface wlan0", "wpa-ssid", "wpa-psk")):
        out.append(("# " + line) if not s.startswith("#") else line)
    else:
        out.append(line)
open(p, "w").writelines(out)
PY

    # ifupdown's own wpa-ssid/wpa-psk handling runs a SEPARATE, dedicated
    # `wpa_supplicant -i wlan0` process outside of NetworkManager entirely
    # (distinct from the D-Bus-controlled instance NetworkManager itself
    # drives). That process exclusively grabs the interface at the netlink
    # level — commenting out the config above doesn't kill an
    # already-running process, so NetworkManager's own wpa_supplicant then
    # fails with "wpa_supplicant couldn't grab this interface" even though
    # the config no longer claims it. Confirmed on real hardware — this was
    # the actual reason the first (properly rolled-back) attempt failed.
    # Stop it explicitly before handing the interface to NetworkManager.
    ifdown wlan0 2>/dev/null || true
    if [[ -f /run/wpa_supplicant.wlan0.pid ]]; then
      kill "$(cat /run/wpa_supplicant.wlan0.pid)" 2>/dev/null || true
    fi
    pkill -f 'wpa_supplicant.*-i wlan0' 2>/dev/null || true
    sleep 1

    systemctl restart NetworkManager
    sleep 3
    nmcli connection up "$SSID" >/dev/null 2>&1 || true

    ok=0
    for _ in $(seq 1 10); do
      if ip -4 addr show wlan0 | grep -q 'inet '; then
        ok=1
        break
      fi
      sleep 1
    done
    if [[ "$ok" -eq 1 ]]; then
      echo "wlan0 now managed by NetworkManager and connected — Wi-Fi scan/connect from the setup screen will work."
    else
      echo "WARNING: NetworkManager did not bring wlan0 up within 10s — rolling back to the working ifupdown config." >&2
      cp -a "${IFACES}.bak-nm-migrate" "$IFACES"
      systemctl restart NetworkManager
      systemctl restart networking 2>/dev/null || true
      ifup wlan0 2>/dev/null || true
      echo "Rolled back — wlan0 is back under ifupdown and should reconnect as before. The setup screen's Wi-Fi tab won't scan until this migration succeeds; re-run this script to retry." >&2
    fi
  else
    echo "wlan0 has an ifupdown stanza but SSID/PSK couldn't be parsed — leaving it alone (Wi-Fi keeps working via ifupdown, just without nmcli scan/connect)." >&2
  fi
fi

echo
echo "If wlan0 appeared, connect with: nmtui   (or: nmcli device wifi connect 'SSID' password 'PASS')"
echo "If not, keep using USB Ethernet and re-check dmesg after reboot."
