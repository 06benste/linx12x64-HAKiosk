# Install Debian on Linx 12X64

Headless Home Assistant kiosk on the Linx 12X64 (Atom x5-Z8350, 4GB).

**Accounts**
- Linux user: `kioskuser`
- Home Assistant user: your choice, set up on the tablet's first-boot setup screen (see §5/§6)

---

## 0. Before you start

- This tablet has **one USB port**. **If you have a USB Ethernet adapter, use it for the install** — it sidesteps needing Wi‑Fi to work at all until after Debian is installed, which is the most reliable path. Without one, Wi‑Fi firmware is injected automatically into the live installer at boot (see §3) so the installer can use Wi‑Fi directly.
- You'll need a second USB stick (≥8 GB) to make the installer, and another PC to prepare it.
- **The installer ISO is the official, unmodified Debian release** — not something this project ships or modifies. You download it straight from Debian and can verify it against Debian's own published checksums (the guided tool below does this for you). The tablet-specific tweaks this project needs (a GPU-crash workaround, and Wi‑Fi firmware) are applied *around* the ISO at boot time via Ventoy, not baked into it — see `ventoy/README.md` if you're curious how.

## 1. Prepare the installer USB

A [Ventoy](https://www.ventoy.net/) USB stick carrying the official Debian netinst ISO, this repo, and a small `ventoy/` folder that applies the GPU-crash boot fix and injects Wi‑Fi firmware into the live installer at boot time, without ever touching the ISO file.

### Guided (Windows, recommended)

`tools/usb_installer_gui.py` does the whole thing for you: downloads and verifies the official ISO, flashes Ventoy onto a USB stick you pick, then copies everything onto it.

1. Insert the USB stick you want to use as the installer (≥8 GB). **Everything on it will be erased.**
2. Run:
   ```powershell
   python tools\usb_installer_gui.py
   ```
3. Under step 1, either click **"Download from cdimage.debian.org…"** (fetches the official ISO directly — the same file you'd get downloading it yourself) or browse to one you already have. Then click **"Verify checksum against Debian's SHA256SUMS"** — it fetches Debian's own published hash for that exact release and compares it against the file on disk, so you get a concrete match/mismatch instead of just trusting a random ISO. The flash button stays disabled until this passes (or you explicitly tick the offline-override checkbox).
4. Under step 2, click **"Download Ventoy from GitHub…"** — fetches the latest release straight from [github.com/ventoy/Ventoy](https://github.com/ventoy/Ventoy), verified against the checksum GitHub publishes alongside it (same treatment as the ISO — Ventoy2Disk.exe runs with disk-write access, so it's checked automatically, no override needed). "ventoy.net (manual)" is there if you'd rather download it yourself.
5. **Only genuine USB removable drives are listed** — the tool asks Windows which disks are on the USB bus and never lets you type a raw disk number, so it can't be pointed at an internal drive by mistake. Pick your stick, type its drive letter to confirm, and click through the final warning.
6. It flashes Ventoy, waits for the new data partition, copies the verified ISO (as `debian-netinst.iso`) + this project + the `ventoy/` boot-fix folder onto it, and writes a `START-HERE.txt`. Your plaintext `credentials.env`, if you have one, is deliberately **not** copied — add it yourself afterward only if you want to pre-bake login (see §6).

### Manual (any OS)

1. Download the official Debian netinst ISO yourself from [cdimage.debian.org](https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/) (or `get.debian.org`) and check it against the `SHA256SUMS` published in the same directory (`certutil -hashfile debian-*.iso SHA256` on Windows, `sha256sum debian-*.iso` on Linux/macOS).
2. Rename it to `debian-netinst.iso` — the boot-fix config in `ventoy/ventoy.json` matches this exact filename.
3. Download **Ventoy** from its [GitHub releases](https://github.com/ventoy/Ventoy/releases) (or ventoy.net) and check the zip against the `sha256.txt` published alongside it, then unzip it.
4. Insert the USB stick you want to use as the installer (≥8 GB). **Everything on it will be erased.**
5. Run Ventoy's installer GUI (`Ventoy2Disk.exe` on Windows, `VentoyGUI.*` on Linux/macOS), select your USB drive, and click **Install**. Confirm the warning.
6. Once Ventoy finishes, the stick shows up as a normal drive. Copy onto it:
   - `debian-netinst.iso` (the official installer, renamed per step 2)
   - the `ventoy/` folder from this repo (goes at the stick **root**, alongside the ISO — not nested inside the project folder)
   - the whole `linx-ha-kiosk` project folder (this repo) — leave `credentials.env` out unless you're intentionally pre-baking login for this tablet

Either way, you should end up with this at the root of the stick:

| Path | Purpose |
|------|---------|
| `debian-netinst.iso` | Official, unmodified Debian installer |
| `ventoy/` | Applies the GPU-crash boot fix and Wi‑Fi firmware injection at boot time (see `ventoy/README.md`) |
| `linx-ha-kiosk/` | This repo — scripts, firmware, setup wizard |

> `scripts/patch_debian_iso.py` / `rebuild_debian_iso.py` / `inject_firmware_initrd.py` are maintainer-only tools for regenerating `ventoy/boot-fix/*.cfg` if a future Debian point release restructures its installer config. `scripts/build_ventoy_firmware_injection.py` rebuilds `ventoy/firmware-inject.tar.gz` if `firmware/brcm/` changes. None of these are part of the normal install flow anymore.

## 2. BIOS

1. Power on and enter BIOS (**Esc**, **F2**, or **Del**).
2. Disable **Secure Boot**.
3. Disable **Fast Boot** if present.
4. Boot from USB (one-time boot menu is fine).

## 3. Boot the installer (Ventoy)

1. In Ventoy, select **`debian-netinst.iso`**.
2. Boot mode: **Normal** (not Grub2, not Memdisk).
3. At the Debian menu, choose **Install** (text) — **not** Graphical install.

### Installer GPU crash (flashing lines)

Cherry Trail often hangs mid-install. The `ventoy/` folder on the stick applies this fix automatically — at boot time, Ventoy swaps in a version of the boot menu with these params added, without ever modifying the ISO file itself:

`intel_idle.max_cstate=1 i915.enable_psr=0 i915.enable_fbc=0 i915.enable_dc=0 i915.enable_rc6=0 nomodeset`

If it still crashes (this automatic swap hasn't been boot-tested on real hardware — see `ventoy/README.md`), do it by hand instead: at the boot menu, edit the line (**e** / **Tab**) and append those params yourself, then continue with **F10** / Enter.

### Missing Wi‑Fi firmware prompt

The `ventoy/` folder on the stick injects the Wi‑Fi firmware directly into the live installer at boot, so this prompt shouldn't appear at all — the installer just finds its Wi‑Fi hardware already working. **Confirmed working on real hardware** (unlike the GPU-crash fix above, which is still unverified).

**If it still appears anyway** (e.g. a future Debian release changes something), don't bother answering "Yes, load from removable media" — on this hardware, the installer does not reliably find files on a Ventoy stick that way even when they're right there (that's how this was originally discovered — hitting exactly this prompt with the files sitting right next to it on the stick). Instead:
- Best option: plug in a **USB Ethernet adapter** and restart the installer, or choose "Configure network manually"/skip past this screen if it lets you continue without Wi‑Fi — you don't need Wi‑Fi during install at all if you have wired network.
- Otherwise, cancel and get Wi‑Fi working after install instead: continue the install choosing "do not configure the network" if offered, finish the base install, then boot into the installed system and run `bash scripts/01-wifi-firmware.sh` from the mounted stick (see §5) before trying `nmtui`.

### If the USB will not boot (32-bit UEFI)

Try other BIOS USB / CSM options. Fallback: Rufus DD-mode of a Debian ISO + `bootia32.efi` in `/EFI/BOOT/`, and keep `linx-ha-kiosk/` on the stick or a microSD.

## 4. Install Debian

| Prompt | Choice |
|--------|--------|
| Language / location | Your locale |
| Hostname | `ha-kiosk` (or similar) |
| User | **`kioskuser`** (remember the password for SSH) |
| Root password | Set one if offered — you’ll need `su -` if `sudo` isn’t installed yet |
| Network / Wi-Fi | Connect now if prompted (you can also do this after first boot with `nmtui`, or later from the tablet's own setup screen's Wi-Fi tab — see §5) |
| Desktop environment | **None** |
| Software | **SSH server** ✅, **standard system utilities** ✅ — nothing else |
| Disk | Entire internal eMMC |
| GRUB | Install to the tablet’s disk / EFI |

## 5. First boot — mount the USB and run scripts

Log in as **`kioskuser`**.

### sudo missing?

Minimal Debian often has no `sudo` if you set a root password:

```bash
su -
apt update
apt install -y sudo
usermod -aG sudo kioskuser
exit
# log out/in, then sudo works
```

Or run the rest as root after `su -` (drop the `sudo` prefix).

### Which partition to mount?

Ventoy creates two partitions:

| Device (typical) | Size | Mount? |
|------------------|------|--------|
| **`sdb1`** | large | **Yes** — ISO + `linx-ha-kiosk` |
| `sdb2` | ~32 MB | No — Ventoy EFI only |

Confirm with `lsblk` (names may be `sda`/`sdb` depending on disks):

```bash
lsblk
su -   # or use sudo if available
mkdir -p /mnt/usb
mount /dev/sdb1 /mnt/usb          # the large Ventoy data partition
ls /mnt/usb/linx-ha-kiosk         # should list scripts/, firmware/, …
cd /mnt/usb/linx-ha-kiosk

bash scripts/install.sh
reboot
```

That one script sets up everything: Wi‑Fi firmware, the kiosk itself, GPU stabilizers, sleep prevention, the power drawer's backend API, the AXP288 charger current-limit fix (without it the tablet slowly discharges overnight even "plugged in"), a battery guard (cleanly shuts the tablet down if it ever hits 1% while actually running on battery, instead of hard-cutting), a secondary guardian (dims the display if battery is low, turns the camera off if it's running hot), and the front camera — in sequence: `01-wifi-firmware.sh` → `02-install-kiosk.sh` → `03-fix-gpu.sh` → `06-no-sleep.sh` → `07-power-drawer.sh` → `10-fix-charger.sh` → `11-battery-guard.sh` → `12-guardian.sh` → `09-install-camera.sh`.

Once it's done, `sudo bash scripts/self-test.sh` checks every local service and endpoint actually came up — worth running before you reboot, and safe to re-run any time later.

**The camera step builds an out-of-tree kernel driver (DKMS)**, so it needs network access. It's last in the sequence so a failure there doesn't take down anything that already succeeded — a warning is printed and the rest of the tablet is left fully working. Skip it entirely with:
```bash
SKIP_CAMERA=1 bash scripts/install.sh
```
(run `sudo bash scripts/09-install-camera.sh` on its own later if you skipped it and change your mind, or if it failed and you want to retry).

Run it even if Wi‑Fi already worked during install (§3) — Debian's installer generally copies firmware it actually used into the freshly installed system, so the base `brcmfmac43455-sdio.*` files *might* already be there. But the Wi-Fi-firmware step also installs two things that are never covered by that: **Bluetooth firmware** (`BCM4345C0_*.hcd`, deliberately left out of the install-time injection since only Wi‑Fi was needed then) and the **screen-rotation sensor hwdb mapping**. It's idempotent either way — safe to run regardless of what's already present. Quick check first if you're curious: `ip link` / `dmesg | grep -i brcm`.

Note there's **no URL argument** above — that's the recommended path for a tablet you're setting up for someone (including yourself) to finish by hand on the touchscreen. `install.sh` forwards its argument straight to `02-install-kiosk.sh`, so to pre-configure the URL: `bash scripts/install.sh 'http://homeassistant.local:8123/dashboard-kiosk'` (see "Pre-configuring instead" below). It expects Linux user **`kioskuser`**; if your account has another name:

```bash
KIOSK_USER=yourname bash scripts/install.sh
```

If you'd rather run the steps individually (e.g. to stop and troubleshoot between them), `install.sh` is just those nine scripts in order — see them directly. Not included in `install.sh` at all: `04-fix-kiosk-autostart.sh` (its fix is already built into `02` by default now) and `05-x11-kiosk.sh` (manual fallback only, if the default Wayland/cage kiosk fails on a particular GPU).

### First boot setup (on the tablet itself)

When the tablet reboots with no HA URL configured, it shows a **setup screen** instead of trying to load a dashboard. This is the same screen the control drawer's **Tablet Setup** button opens later (§10) — it has four tabs:

- **Home Assistant** — enter your dashboard URL, and optionally a username/password for autofill. There's a "Test connection" button, and a built-in help panel covering how to find your URL and how to set up HA-side auth (see §6 for the same content).
- **Wi-Fi** — scan and connect if you skipped Wi-Fi during install.
- **MQTT** — broker host/username/password and a switch to publish this tablet as an HA device via MQTT Discovery (see §10 for what that adds).
- **Cameras** — power the front camera on/off, switch front/rear, live preview, and grade sliders (exposure, white balance, etc.) — only present if the camera step of install.sh ran.

Tap **Save & continue** on the Home Assistant tab and the tablet restarts straight into your dashboard. This needs a keyboard (the tablet's cover keyboard, or USB/Bluetooth) — the same requirement the Debian installer itself already has, there's no on-screen keyboard bundled.

### Pre-configuring instead (advanced / deploying many tablets)

If you're setting up several tablets for one house and don't want to type the URL on each one by hand, pass it on the command line and it'll skip the setup screen entirely:

```bash
bash scripts/install.sh 'http://homeassistant.local:8123/dashboard-kiosk'
```

For autofill login too, create `credentials.env` next to the scripts (see `credentials.env.example`) before running `install.sh` — it gets baked in at install time. Whatever's typed into the on-tablet setup screen later will overwrite this if the tablet is ever reconfigured.

## 6. Home Assistant side

### Use a dedicated tablet account

Create a separate, **non-admin** user in HA for this tablet: **Settings → People → Add Person**, leave "Administrator" unchecked. If you use the setup screen's Username/Password fields, that password is stored in plain text under `/opt/ha-kiosk/` on the tablet — don't point it at your main admin account.

### Simple: autofill login

Type the username/password into the tablet's setup screen (or pre-bake `credentials.env`, see §5). A small Chromium extension fills the HA login form on first load.

### Better: Trusted Networks

Leave the username/password blank on the tablet and add this to the HA host's `configuration.yaml` instead:

```yaml
homeassistant:
  auth_providers:
    - type: trusted_networks
      trusted_networks:
        - 192.168.8.0/24
      trusted_users:
        192.168.8.0/24: KIOSK_USER_ID
      allow_bypass_login: true
    - type: homeassistant
```

Replace `KIOSK_USER_ID` from **Settings → People → your tablet user**, and the CIDR range with your own LAN. Restart HA. No password ever touches the tablet.

### Hiding the sidebar

Install HACS **Kiosk Mode** (`NemesisRE/kiosk-mode`) and add to `configuration.yaml`:

```yaml
frontend:
  extra_module_url:
    - /hacsfiles/kiosk-mode/kiosk-mode.js
```

The tablet's extension appends `?kiosk` to the dashboard URL automatically (hides sidebar + header) — you don't need to add it yourself when typing the URL into the setup screen. Use `?hide_sidebar` instead if you want to keep the top header; type that variant into the setup screen's URL field.

## 7. Wi‑Fi still failing

Wi‑Fi should already be working at this point (firmware injected during install, §3; `01-wifi-firmware.sh` run in §5). If it isn't:

```bash
dmesg | grep -i brcm
ls -l /lib/firmware/brcm/brcmfmac43455*
modprobe -r brcmfmac; modprobe brcmfmac
ip link
nmtui
```

Or once the kiosk is running, use the control drawer's **Tablet Setup** button → Wi-Fi tab (see §10) instead of SSH.

## 8. Flashing lines after install

```bash
bash /mnt/usb/linx-ha-kiosk/scripts/03-fix-gpu.sh
# or:
bash /opt/ha-kiosk/scripts/03-fix-gpu.sh
reboot
```

If it still corrupts, keep/add `nomodeset` in GRUB (`update-grub`).

## 9. Screen sleeps / tablet suspends when idle

Keep it awake on AC:

```bash
su -
mount /dev/sdb1 /mnt/usb   # large Ventoy partition
cd /mnt/usb/linx-ha-kiosk
sed -i 's/\r$//' scripts/*.sh
bash scripts/06-no-sleep.sh
reboot
```

This masks suspend/hibernate, tells logind to ignore idle/lid, and disables console blanking.

## 10. Maintenance

### Reconfiguring later (no SSH needed)

Open the control drawer on the tablet (tap the tab on the right edge of the screen). Near the top:
- **Camera power** — a quick on/off switch, separate from the settings tabs below since it's the one thing you'll flip often. Turning it off stops the camera-stream service entirely (no image published anywhere, MQTT included) rather than just hiding it in the UI.
- **Tablet Setup** — opens the same four-tab screen as first boot (§5) without leaving the dashboard: Home Assistant, Wi-Fi, MQTT, Cameras. Saving on any tab merges in the change; nothing here clears what's already configured, so there's no "disconnect and start over" step to worry about triggering by accident.

The MQTT tab is off by default; needs a broker (e.g. the Mosquitto add-on) and a dedicated MQTT user first. The `python3-paho-mqtt` package and bridge files are already installed by `07-power-drawer.sh` — this screen just supplies credentials and flips the systemd service on/off.

### Via SSH

```bash
ssh kioskuser@ha-kiosk.local

echo 'http://NEW-URL' | sudo tee /opt/ha-kiosk/url
sudo systemctl restart getty@tty1
```

### LAN access and the API token

`power-api.py` (17823) and `camera-stream-server.py` (17824) both listen on every network interface, not just the tablet itself — Home Assistant's REST sensors and live mjpeg camera (`homeassistant/hakiosk.yaml`, `ha/kiosk_camera_stream.yaml`) need to reach them from across the LAN. `07-power-drawer.sh` generates a shared token at `/opt/ha-kiosk/api.token` for exactly that: anything calling either service from another machine needs to send it (`Authorization: Bearer <token>`, or `?token=<token>` for the mjpeg URL, which can't send custom headers); requests from the tablet itself (the drawer, the setup screen, the MQTT bridge) never need it. If you've copied either HA package file into your real config, paste the token into HA's `secrets.yaml` as shown in the comments at the top of those files. Deleting `/opt/ha-kiosk/api.token` (and not setting `KIOSK_API_TOKEN`/`CAMERA_STREAM_TOKEN`) reverts to the old open-LAN behavior.

`setup-wizard.py` (17825) is different: it has no auth at all — a POST there can rewrite the tablet's HA URL/login, Wi-Fi credentials, or MQTT broker credentials — so it's bound to `127.0.0.1` only by default instead. Nothing legitimate needs to reach it from another machine (both the drawer's overlay and the first-boot page already run in the tablet's own browser); override `SETUP_WIZARD_HOST` only if you specifically need to drive setup remotely, understanding that opens config-rewrite access to the whole LAN.

### Battery and thermal safety

Two always-on daemons watch the fuel gauge and thermal sensors independently of everything else:
- **`ha-kiosk-battery-guard.service`** cleanly shuts the tablet down (`systemctl poweroff`) the moment capacity hits 1% while net-discharging — checked against the battery's own charge/discharge status, not just whether a cable is plugged in, since an inadequate charger can leave it discharging the entire time it reads as "plugged in". Deliberately dependency-free (reads `/sys/class/power_supply` directly) so it still works if everything else on the tablet is unhappy.
- **`ha-kiosk-guardian.service`** handles softer mitigations: dims the display to 15% once battery drops to 20% and is discharging, and turns the camera off if CPU/SoC temperature stays at or above 85°C for a sustained stretch. Both conditions are also visible from Home Assistant (`binary_sensor.hakiosk_charger_inadequate`, `sensor.hakiosk_cpu_temperature`) if MQTT is enabled, and the drawer's battery chip turns amber/red for the same thresholds.

### Updating an already-installed tablet

For changes to the fast-moving runtime files (the Python services, the setup wizard's HTML, the chromium extension) — not Wi-Fi firmware, the GPU fix, or the camera's kernel driver, which change rarely and need their own scripts re-run directly on the tablet — `tools/deploy_to_tablet.py` pushes an updated checkout to a tablet over SSH and restarts whatever it touched, from a dev machine with network access to it:

```powershell
python tools\deploy_to_tablet.py <tablet-ip> --all
# or just one thing:
python tools\deploy_to_tablet.py <tablet-ip> --only power-api
```

Needs `pip install paramiko` on the machine running it; nothing extra on the tablet. Run `sudo bash scripts/self-test.sh` on the tablet afterward to confirm everything came back up.
