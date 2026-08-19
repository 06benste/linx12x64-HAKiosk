#!/usr/bin/env bash
# Stabilize Intel Cherry Trail (Atom Z8350) graphics — stops line-corruption / GPU hangs.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

PARAMS=(
  # max_cstate=0 is more reliable than 1 on some Z8350 hangs
  intel_idle.max_cstate=0
  i915.enable_psr=0
  i915.enable_fbc=0
  i915.enable_dc=0
  idle=nomwait
)

GRUB_FILE=/etc/default/grub
if [[ ! -f "$GRUB_FILE" ]]; then
  echo "No $GRUB_FILE — not a GRUB system?" >&2
  exit 1
fi

# Backup once
[[ -f ${GRUB_FILE}.bak-linx ]] || cp -a "$GRUB_FILE" "${GRUB_FILE}.bak-linx"

current="$(grep -E '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUB_FILE" | head -n1 || true)"
if [[ -z "$current" ]]; then
  echo 'GRUB_CMDLINE_LINUX_DEFAULT=""' >>"$GRUB_FILE"
  current='GRUB_CMDLINE_LINUX_DEFAULT=""'
fi

# Extract existing quoted value
val="$(sed -n 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/\1/p' "$GRUB_FILE" | head -n1)"
for p in "${PARAMS[@]}"; do
  key="${p%%=*}"
  # drop any existing key=... then append
  val="$(echo "$val" | sed -E "s/(^| )${key}=[^ ]*//g" | xargs)"
  val="${val} ${p}"
done
val="$(echo "$val" | xargs)"

# Rewrite the line
tmp="$(mktemp)"
awk -v newval="$val" '
  BEGIN { done=0 }
  /^GRUB_CMDLINE_LINUX_DEFAULT=/ && !done {
    print "GRUB_CMDLINE_LINUX_DEFAULT=\"" newval "\""
    done=1
    next
  }
  { print }
  END {
    if (!done) print "GRUB_CMDLINE_LINUX_DEFAULT=\"" newval "\""
  }
' "$GRUB_FILE" >"$tmp"
mv "$tmp" "$GRUB_FILE"

# Blacklist problematic optional modules sometimes tied to hangs — but not if
# the front camera has already been set up. 09-install-camera.sh overwrites
# this same file with a permissive policy so atomisp can load; if this script
# is ever re-run standalone afterward (e.g. chasing a later flashing-lines
# report per docs/INSTALL.md §8), blindly rewriting it here would silently
# put the blacklist back and break the camera on the next reboot.
mkdir -p /etc/modprobe.d
if [[ ! -f /etc/systemd/system/ha-kiosk-atomisp.service ]]; then
  cat >/etc/modprobe.d/blacklist-atomisp.conf <<'EOF'
# Cherry Trail camera ISP — can cause boot/GPU instability on some kernels
blacklist atomisp
blacklist atomisp_gmin_platform
options atomisp blacklist=1
EOF
else
  echo "Camera already installed — leaving atomisp modprobe policy untouched."
fi

update-grub

echo
echo "Cherry Trail GPU stabilizers applied:"
echo "  $val"
echo
echo "Reboot required: sudo reboot"
echo "If it still corrupts, next step is adding nomodeset (slower, but stable)."
