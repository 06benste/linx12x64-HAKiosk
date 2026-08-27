# Linx 12X64 → Home Assistant Linux Kiosk

Turn a wiped **Linx 12X64** (Atom x5-Z8350, 4GB) into a dedicated Home Assistant wall panel on Debian.

> **Transparency note:** Claude (Anthropic's AI) had a significant hand in developing this project — code, scripts, and docs alike. Every change was directed, reviewed, and extensively tested on real hardware by the maintainer; nothing here shipped unverified.

## You do not need the old Windows drivers

This repo includes the Linx-specific Broadcom 43455 firmware (sourced from community Linx 12X64 archives):

| File | Purpose |
|------|---------|
| `firmware/brcm/brcmfmac43455-sdio.txt` | NVRAM (from `4345r6nvram.txt`) |
| `firmware/brcm/brcmfmac43455-sdio.clm_blob` | Country/locale blob |
| `firmware/brcm/BCM4345C0_*.hcd` | Bluetooth firmware (optional) |
| `firmware/61-sensor-local.hwdb` | Screen rotation sensor mapping |

## What you need

1. **USB Ethernet adapter** (strongly recommended for first boot) — tablet has full-size USB 3.0 + micro‑USB
2. USB stick (≥8GB) for the Debian installer (see [docs/INSTALL.md §1](docs/INSTALL.md#1-prepare-the-installer-usb) for how to flash it with Ventoy). This uses the **official, unmodified Debian ISO** and **Ventoy fetched straight from its GitHub releases** — `tools/usb_installer_gui.py` downloads both directly from cdimage.debian.org and github.com/ventoy/Ventoy and verifies each against its publisher's own checksum, so you're never asked to trust a project-provided blob.
3. Another PC to prepare that stick
4. Your Home Assistant dashboard URL — you don't need this yet; the tablet will ask for it on first boot

## Quick path

1. Follow [docs/INSTALL.md](docs/INSTALL.md) — flashing the USB, BIOS, 32‑bit EFI note, Debian install
2. Copy this project onto the tablet (USB/microSD)
3. Run:
   ```bash
   sudo bash scripts/install.sh
   sudo reboot
   ```
   (one script — Wi‑Fi firmware, the kiosk, GPU stabilizers, sleep prevention, power-drawer backend, charger fix, battery/thermal safety daemons, and the front camera, all in one run. The camera step builds a kernel driver and needs network access; skip it with `SKIP_CAMERA=1 sudo bash scripts/install.sh` and run it later on its own)
4. On first boot, finish setup on the tablet's touchscreen — enter your Home Assistant URL (and optional login), it restarts straight into your dashboard. See [docs/INSTALL.md §5](docs/INSTALL.md#5-first-boot--mount-the-usb-and-run-scripts).

Deploying several tablets for one house and don't want to type the URL on each? Pass it directly: `sudo bash scripts/install.sh 'http://homeassistant.local:8123/dashboard-kiosk'` — see docs for pre-baking login credentials too.

## Stack

- Debian 13 (Trixie) netinst (minimal / no desktop) — also on the Ventoy USB
- `cage` (single-app Wayland compositor)
- Chromium kiosk mode
- Autologin on TTY1
