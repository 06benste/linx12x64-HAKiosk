# Install Debian on Linx 12X64

Headless Home Assistant kiosk on the Linx 12X64 (Atom x5-Z8350, 4GB).


## 0. Before you start

- You'll need a USB stick (≥8 GB) to make the installer, and a PC to prepare it.
- **The installer ISO is the official, unmodified Debian release** — not something this project ships or modifies. You download it straight from Debian and can verify it against Debian's own published checksums (the guided tool below does this for you). The tablet-specific tweaks this project needs (a GPU-crash workaround, and Wi‑Fi firmware) are applied *around* the ISO at boot time via Ventoy, not baked into it — see `ventoy/README.md` if you're curious how.

## 1. Prepare the installer USB

A [Ventoy](https://www.ventoy.net/) USB stick carrying the official Debian netinst ISO, this repo, and a small `ventoy/` folder that applies the GPU-crash boot fix and injects Wi‑Fi firmware into the live installer at boot time, without ever touching the ISO file.

### Guided (Windows, recommended)

`tools/usb_installer_gui.py` does the whole thing for you: downloads and verifies the official ISO, flashes Ventoy onto a USB stick you pick, then copies everything onto it.

1. Insert the USB stick you want to use as the installer (≥8 GB). **Everything on it will be erased.**
2. open Powershell, CD to the downloaded release and run:
   python tools\usb_installer_gui.py

3. Under step 1, click **"Download latest (verified)"** — always fetches whatever Debian's `current` release is, and checks it against Debian's own published SHA256SUMS automatically as part of the download. Or browse to an ISO you already have.
4. Under step 2, click **"Download latest Ventoy"** — fetches the latest release straight from [github.com/ventoy/Ventoy](https://github.com/ventoy/Ventoy).
5. Pick your USB stick from the list and click through the final "erase this disk, are you sure" warning.
6. It flashes Ventoy, waits for the new data partition, copies the verified ISO (as `debian-netinst.iso`) + this project + the `ventoy/` boot-fix folder onto it, and writes a `START-HERE.txt`. 


## 2. BIOS

1. Power on and enter BIOS (**Esc**, **F2**, or **Del**).
2. Disable **Secure Boot**.
3. Disable **Fast Boot** if present.
4. Boot from USB (one-time boot menu is fine).

## 3. Boot the installer (Ventoy)

1. In Ventoy, select **`debian-netinst.iso`**.
2. Boot mode: **Normal** (not Grub2, not Memdisk).
3. At the Debian menu, choose **Install** (text) — **not** Graphical install.


## 4. Install Debian

| Prompt | Choice |
|--------|--------|
| Language / location | Your locale |
| Hostname | `ha-kiosk` (or similar) |
| User | **`kioskuser`** (remember the password for SSH) |
| Root password | Set one — required, since this guide uses `su -` for admin commands rather than `sudo` |
| Network / Wi-Fi | Connect now if prompted (you can also do this after first boot with `nmtui`, or later from the tablet's own setup screen's Wi-Fi tab — see §5) |
| Software selection (tasksel) | Uncheck ⬜ **Debian desktop environment** and every sub-item under it (GNOME, Xfce, KDE Plasma, Cinnamon, MATE, LXDE, LXQt — whichever are ticked by default) —  Uncheck ⬜ **web server** and ⬜ **print server** if either is ticked — nothing here serves or prints. Leave **SSH server** ✅ ticked — see "Is SSH required?" below. Leave **standard system utilities** ✅ ticked (default) — later scripts assume the usual base tools are present. | Use the space bar to check/uncheck items
| Disk | Entire internal eMMC |
| GRUB | Install to the tablet’s disk / EFI |

### Is SSH required?

Yes, in practice. There's no on-screen keyboard until this project's own setup wizard is installed, so unless you plan to keep a USB/Bluetooth keyboard attached to the tablet the whole time, SSH is your only way to type anything at it. It's used for:
- **§5, first boot** — logging into the freshly installed tablet from another PC to mount the USB stick and run `scripts/install.sh`, with no keyboard needed on the tablet itself.
- **Later updates** — `tools/deploy_to_tablet.py` (§10) pushes code/config changes and restarts services over SSH.
- **Fallback maintenance** — the "Via SSH" path in §10 for anything the on-screen control drawer / setup wizard doesn't cover.

If you do keep a keyboard attached to the tablet permanently, you can uncheck SSH server and do all of the above at the tablet's own console instead — just replace every `ssh kioskuser@ha-kiosk.local` command in this guide with typing it directly.

## 5. First boot — mount the USB and run scripts

Log in as **`kioskuser`**.

### Becoming root

This guide uses `su -` for admin commands rather than `sudo` — a minimal Debian install has no `sudo` installed by default anyway, and you already set a root password in §4. Run `su -`, enter it, and stay in that shell for the commands below; for one-off commands elsewhere in this guide, `su -c '<command>'` runs just that one as root.

### Which partition to mount?

There will be 2 partitions on the install USB:
| Device (typical) | Size | Mount? |
|------------------|------|--------|
| **`sda1`** | large | **Yes** — ISO + `linx-ha-kiosk` |
| `sda2` | ~32 MB | No — Ventoy EFI only |

Confirm with `lsblk` (names may be `sda`/`sdb` depending on disks):

```bash
su -
lsblk
mkdir -p /mnt/usb
mount /dev/sda1 /mnt/usb #use the correct partition identified using lsblk
ls /mnt/usb/linx-ha-kiosk # should list scripts/, firmware/, …
cd /mnt/usb/linx-ha-kiosk

bash scripts/install.sh
reboot
```

That one script sets up all tablet functionality and makes appropriate firmware fixes.



### First boot setup (on the tablet itself)

When the tablet reboots with no HA URL configured, it shows a **setup screen** instead of trying to load a dashboard. This is the same screen the control drawer's **Tablet Setup** button opens later (§10) — it has four tabs:

- **Home Assistant** — enter your dashboard URL, and a username/password for login (it is reccomended to create a specific kiosk user in your Home Assistant instance). There's a "Test connection" button, and a built-in help panel.
- **Wi-Fi** — scan and connect if you skipped Wi-Fi during install or wish to change connected network.
- **MQTT** — broker host/username/password and a switch to publish this tablet as an HA device via MQTT Discovery (see §10 for what that adds).
- **Cameras** — power the front camera on/off, switch front/rear, live preview, and grade sliders (exposure, white balance, etc.). **Camera functionality is currently in alpha and has unsustainable power drawer. It is reccomended that cameras remain turned off generally.**

Tap **Save & continue**.


## 6. Home Assistant side

### Use a dedicated tablet account

Create a separate, **non-admin** user in HA for this tablet: **Settings → People → Add Person**, leave "Administrator" unchecked. If you use the setup screen's Username/Password fields, that password is stored in plain text under `/opt/ha-kiosk/` on the tablet — don't point it at your main admin account.

### Simple: autofill login

Type the username/password into the tablet's setup screen.

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

Replace `KIOSK_USER_ID` from **Settings → People → your tablet user**, and the IP range with your own LAN. Restart HA.

### Hiding the sidebar

Install HACS **Kiosk Mode** (`NemesisRE/kiosk-mode`) and add to `configuration.yaml`:

```yaml
frontend:
  extra_module_url:
    - /hacsfiles/kiosk-mode/kiosk-mode.js
```

The tablet's extension appends `?kiosk` to the dashboard URL automatically (hides sidebar + header) — you don't need to add it yourself when typing the URL into the setup screen. Use `?hide_sidebar` instead if you want to keep the top header; type that variant into the setup screen's URL field.

