# ventoy/

Applies the tablet-specific boot fixes to the **official, unmodified** Debian
netinst ISO at boot time, via Ventoy's `conf_replace` plugin — the ISO file
itself is never touched, so it stays byte-for-byte identical to what Debian
publishes (verifiable against Debian's own SHA256SUMS).

- `ventoy.json` — an `injection` rule plus five `conf_replace` rules, all
  matched against a stick-root file named exactly `debian-netinst.iso` (see
  `tools/usb_installer_gui.py`, which copies the verified ISO under that fixed
  name for this reason).
- `firmware-inject.tar.gz` — the tablet's Broadcom Wi-Fi firmware
  (`firmware/brcm/`), extracted by Ventoy's Injection plugin straight into the
  live installer's initramfs at `/lib/firmware/brcm/` *before* the installer's
  own "Detect network hardware" firmware prompt runs — so it just finds the
  firmware already present and never has to prompt at all.

  **This replaces relying on the installer's "load firmware from removable
  media" prompt.** That was the original plan (point it at the loose
  `firmware/brcm/` folder on the same stick) but it does not reliably work on
  a Ventoy data partition on this hardware — confirmed by an actual install
  attempt where the installer couldn't find the files even though they were
  right there on the stick. Injection puts the files directly into the
  environment the installer already reads from, sidestepping that removable-
  media detection step entirely. Regenerate with
  `scripts/build_ventoy_firmware_injection.py` if `firmware/brcm/` changes.
- `boot-fix/*.cfg` — the Debian installer's own isolinux/grub boot configs,
  each with the Cherry Trail GPU-crash kernel params appended to every
  `append`/`linux` line: `intel_idle.max_cstate=1 i915.enable_psr=0
  i915.enable_fbc=0 i915.enable_dc=0 i915.enable_rc6=0 nomodeset`.
  - `txt.cfg`, `adtxt.cfg` — legacy/BIOS text-mode install + advanced text menu
  - `gtk.cfg`, `adgtk.cfg` — legacy/BIOS graphical install + advanced graphical menu
  - `grub.cfg` — UEFI, covers *all* menu entries (Debian's `EFI/debian/grub.cfg`
    and `boot/grub/x86_64-efi/grub.cfg` are just one-line `source` stubs that
    both resolve to this one file, confirmed by reading a real extracted ISO)

Each file was diffed against the matching file inside the real, mounted
`debian-13.6.0-amd64-netinst.iso` to confirm the *only* change is the appended
kernel params — no other content drift.

## Regenerating these files for a new Debian point release

Debian occasionally restructures its installer config between releases. If
these fixes stop applying (tablet boots into the unpatched GPU-crash bug),
regenerate:

1. Download the new official netinst ISO.
2. Mount it (Windows: `Mount-DiskImage`; Linux: `mount -o loop`).
3. Diff its `isolinux/{txt,gtk,adtxt,adgtk}.cfg` and `boot/grub/grub.cfg`
   against the versions here to see what Debian changed structurally.
4. Re-append the kernel params to the new files' `append`/`linux` lines and
   replace the files in `boot-fix/`.

`scripts/patch_debian_iso.py` / `rebuild_debian_iso.py` /
`inject_firmware_initrd.py` do the equivalent patching by remastering a whole
ISO — useful as a reference for the exact param list, but not part of the
end-user install flow anymore.

## If the automatic fix doesn't take

Neither plugin has been boot-tested end-to-end on real hardware as part of
adding this (the injection mechanism is documented as Ventoy's own headline
use case — driver injection — so it's on firmer ground than the boot-param
`conf_replace`, which is more speculative). If something doesn't apply:

- **GPU corruption ("flashing lines") during install**: fall back to the
  manual fix in `docs/INSTALL.md` §3 — press `e` (or `Tab` at the isolinux
  prompt) at the boot menu and append the params above by hand.
- **Wi-Fi firmware prompt still appears / still can't find the files**: the
  most reliable fallback is a USB Ethernet adapter for the install itself
  (sidesteps needing Wi-Fi during install entirely — see `docs/INSTALL.md`
  §0), then run `scripts/01-wifi-firmware.sh` after first boot to get Wi-Fi
  working post-install.
