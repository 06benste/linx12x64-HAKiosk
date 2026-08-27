#!/usr/bin/env python3
"""
Guided USB installer builder for the Linx HA kiosk project (Windows only).

Flashes a Ventoy USB stick and copies the Debian installer ISO + this repo
onto it, so an end user just needs to plug the stick into the tablet — no
manual Ventoy GUI steps, no drag-and-drop.

Safety: the drive picker only ever lists disks Windows reports as USB-bus
removable media (via PowerShell Get-Disk), and the physical drive index used
for flashing always comes from that same filtered list — never free-typed —
so this can't be pointed at an internal disk by a typo or stale index. A
modal "erase this disk, are you sure" confirmation still gates the actual
flash/erase.

Requires Administrator to even open (see the bottom of this file) — raw disk
writes need it, and elevating reactively later meant relaunching mid-workflow
as a brand new process, throwing away everything already filled in.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

if sys.platform != "win32":
    raise SystemExit("usb_installer_gui.py is Windows-only (uses PowerShell Get-Disk and Ventoy2Disk.exe).")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin() -> None:
    """Re-invoke this same script elevated (triggers the UAC prompt), since
    writing to a physical disk — what Ventoy2Disk.exe does — requires it.
    Windows itself refuses with WinError 740 otherwise."""
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "downloads"
VENTOY_URL = "https://www.ventoy.net/en/download.html"
# Fetched straight from Ventoy's own GitHub releases rather than pointing the
# user at the website — GitHub also publishes a sha256.txt per release, so
# this gets the same download-and-verify treatment as the Debian ISO below.
# (Ventoy2Disk.exe runs with disk-write privileges, so if anything deserves
# verifying, it's this.)
VENTOY_GITHUB_LATEST_API = "https://api.github.com/repos/ventoy/Ventoy/releases/latest"

# We deliberately use the *official*, unmodified Debian ISO — not a project-
# provided one — so it can be checked against Debian's own published
# checksums. The GPU-crash boot params and other tweaks that used to be baked
# into a remastered ISO are applied instead by ventoy/ventoy.json (Ventoy's
# conf_replace plugin), which swaps specific boot-config files at boot time
# without ever touching the ISO on disk. See ventoy/README.md.
DEBIAN_ISO_DIR_TMPL = "https://cdimage.debian.org/debian-cd/{version}/amd64/iso-cd/"
# cdimage's "current" is a symlink that always points at whatever the latest
# stable release directory is — reading it means never hardcoding/tracking a
# version number here at all.
DEBIAN_CURRENT_ISO_DIR = "https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/"
ISO_FILENAME_RE = re.compile(r"^debian-([\d.]+)-amd64-netinst\.iso$")
# ventoy.json's conf_replace rules match this exact filename — copying the
# verified ISO onto the stick under a fixed name avoids needing Ventoy's
# wildcard/fuzzy image-matching syntax for whatever version string Debian's
# own filename happens to carry.
FIXED_ISO_NAME = "debian-netinst.iso"

# Dirs never copied onto the stick — dev scratch, VCS, build junk, editor state.
COPY_EXCLUDE_DIRS = {
    "downloads", "logs", "tmp_cam_diag", ".git", ".vs",
    "__pycache__", "iso-work", "ventoy", ".claude",
}
# Files never copied — secrets and personal-machine notes that shouldn't ride
# along to someone else's tablet. credentials.env in particular: the project's
# own .gitignore excludes it from git for the same reason.
COPY_EXCLUDE_FILES = {"credentials.env", "ha-credentials.env", "ha-url.txt"}


def run_ps(script: str, timeout: float = 30) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"powershell exited {r.returncode}")
    return r.stdout.strip()


@dataclass
class UsbDisk:
    number: int
    friendly_name: str
    size_bytes: int
    drive_letters: str

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / (1024 ** 3), 1)

    def label(self) -> str:
        letters = f" ({self.drive_letters})" if self.drive_letters else ""
        return f"Disk {self.number}: {self.friendly_name} — {self.size_gb} GB{letters}"


def list_usb_disks() -> list[UsbDisk]:
    script = (
        "Get-Disk | Where-Object { $_.BusType -eq 'USB' } | ForEach-Object { "
        "$d = $_; $letters = @(Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue "
        "| Where-Object { $_.DriveLetter } | ForEach-Object { \"$($_.DriveLetter):\" }); "
        "[PSCustomObject]@{ Number = $d.Number; FriendlyName = $d.FriendlyName; "
        "SizeBytes = $d.Size; DriveLetters = ($letters -join ',') } } | ConvertTo-Json -Compress"
    )
    out = run_ps(script)
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    return [
        UsbDisk(number=d["Number"], friendly_name=d["FriendlyName"] or "USB drive",
                size_bytes=d["SizeBytes"], drive_letters=d.get("DriveLetters") or "")
        for d in data
    ]


def find_data_partition_letter(disk_number: int, timeout: float = 60) -> str:
    """After Ventoy formats the disk, find the large data partition's drive letter."""
    script = (
        f"Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DriveLetter } | "
        "Select-Object DriveLetter, Size | ConvertTo-Json -Compress"
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = run_ps(script)
        if out:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            # Ventoy always leaves exactly two partitions after flashing: the big
            # data partition and a ~32MB VTOYEFI one. Pick the largest rather than
            # the first match — order isn't guaranteed, and this stays correct
            # even if a stray extra partition happens to also clear the threshold.
            big = [p for p in data if p.get("Size", 0) > 500 * 1024 * 1024]
            if big:
                largest = max(big, key=lambda p: p.get("Size", 0))
                return f"{largest['DriveLetter']}:"
        time.sleep(2)
    raise RuntimeError("Timed out waiting for the Ventoy data partition to appear")


def find_ventoy_exe() -> Path | None:
    for candidate in DOWNLOADS.glob("ventoy*/**/Ventoy2Disk.exe"):
        return candidate
    for candidate in DOWNLOADS.glob("ventoy/**/Ventoy2Disk.exe"):
        return candidate
    return None


def copy_file_with_progress(src: Path, dest: Path, progress) -> None:
    """Like shutil.copy2, but logs percentage — writes to a USB stick are slow
    enough (especially older/slower sticks) that a silent multi-hundred-MB
    copy looks hung without this."""
    total = src.stat().st_size
    written = 0
    last_pct = -1
    with open(src, "rb") as fsrc, open(dest, "wb") as fdst:
        while True:
            buf = fsrc.read(4 * 1024 * 1024)
            if not buf:
                break
            fdst.write(buf)
            written += len(buf)
            if total:
                pct = int(written * 100 / total)
                if pct != last_pct:
                    progress(f"  {pct}%  ({written // (1024*1024)} / {total // (1024*1024)} MB)")
                    last_pct = pct
    shutil.copystat(src, dest)


def find_default_iso() -> Path | None:
    """Prefer an official-named netinst ISO already downloaded; never the old
    project-remastered variant (kept around for maintainers, not end users)."""
    candidates = sorted(
        p for p in DOWNLOADS.glob("debian-*-amd64-netinst.iso")
        if "linxfw" not in p.name and "firmware" not in p.name
    )
    return candidates[-1] if candidates else None


def official_iso_filename(version: str) -> str:
    return f"debian-{version}-amd64-netinst.iso"


def official_iso_dir_url(version: str) -> str:
    return DEBIAN_ISO_DIR_TMPL.format(version=version.strip())


def download_url(url: str, dest: Path, progress) -> None:
    """Stream a URL to disk with progress, atomically (via a .part temp file)."""
    progress(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "linx-ha-kiosk-usb-installer/1.0"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            read = 0
            last_pct = -1
            while True:
                buf = resp.read(1024 * 256)
                if not buf:
                    break
                f.write(buf)
                read += len(buf)
                if total:
                    pct = int(read * 100 / total)
                    if pct != last_pct:
                        progress(f"  {pct}%  ({read // (1024*1024)} / {total // (1024*1024)} MB)")
                        last_pct = pct
    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed: HTTP {exc.code} for {url}") from exc
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)
    progress("Download complete.")


def version_from_iso_filename(name: str) -> str | None:
    m = ISO_FILENAME_RE.match(name)
    return m.group(1) if m else None


def resolve_latest_debian() -> tuple[str, str]:
    """(version, filename) for whatever cdimage's current/ symlink points at
    right now — read from its own SHA256SUMS listing rather than scraping an
    HTML directory index, since that file has to exist and be accurate
    anyway for verification."""
    text = fetch_url_text(DEBIAN_CURRENT_ISO_DIR + "SHA256SUMS", timeout=20)
    for line in text.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        _digest, name = parts
        name = name.lstrip("*").strip()
        version = version_from_iso_filename(name)
        if version:
            return version, name
    raise RuntimeError("No netinst ISO found in cdimage's current SHA256SUMS listing")


def download_latest_debian(dest_dir: Path, progress) -> tuple[Path, str]:
    """Resolve + download + verify the current Debian netinst in one go —
    folds what used to be a separate manual "Verify checksum" click into the
    download itself, since the checksum lookup already has to happen here
    either way to know the exact filename to fetch."""
    progress("Checking cdimage.debian.org for the current release ...")
    version, filename = resolve_latest_debian()
    progress(f"Latest: Debian {version}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    download_url(DEBIAN_CURRENT_ISO_DIR + filename, dest, progress)
    progress("Fetching official checksum ...")
    expected = fetch_official_sha256(version, filename)
    actual = sha256_of_file(dest, progress)
    if actual != expected:
        dest.unlink(missing_ok=True)
        raise RuntimeError("Downloaded ISO does NOT match Debian's published checksum — refusing to use it.")
    progress("Checksum verified — matches Debian's official release.")
    return dest, version


def fetch_url_text(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "linx-ha-kiosk-usb-installer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_sha256sums(text: str, filename: str) -> str:
    """Parse a standard `<hex>  <filename>` checksum listing (works for both
    Debian's SHA256SUMS and GitHub release sha256.txt files) and return the
    hex digest for `filename`."""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts
        name = name.lstrip("*").strip()
        if name == filename:
            return digest.lower()
    raise RuntimeError(f"{filename} not found in checksum listing")


def fetch_latest_ventoy_release() -> dict:
    """Query GitHub's API for the latest Ventoy release and return its version
    plus the Windows zip / checksum asset URLs."""
    text = fetch_url_text(VENTOY_GITHUB_LATEST_API, timeout=20)
    data = json.loads(text)
    version = str(data.get("tag_name", "")).lstrip("v")
    if not version:
        raise RuntimeError("GitHub API response had no tag_name")
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    zip_name = f"ventoy-{version}-windows.zip"
    if zip_name not in assets:
        raise RuntimeError(f"{zip_name} not found in latest Ventoy release assets")
    if "sha256.txt" not in assets:
        raise RuntimeError("sha256.txt not found in latest Ventoy release assets")
    return {
        "version": version,
        "zip_name": zip_name,
        "zip_url": assets[zip_name],
        "sha256_url": assets["sha256.txt"],
    }


def download_and_verify_ventoy(dest_dir: Path, progress) -> Path:
    """Download the latest Ventoy release from GitHub, verify it against
    GitHub's own published sha256.txt, extract it, and return the path to
    Ventoy2Disk.exe. Raises if the checksum doesn't match — this is an
    executable that runs with disk-write privileges, so it's verified
    unconditionally, not behind an optional/override step like the ISO."""
    progress("Checking GitHub for the latest Ventoy release ...")
    release = fetch_latest_ventoy_release()
    progress(f"Latest Ventoy release: v{release['version']}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / release["zip_name"]
    download_url(release["zip_url"], zip_path, progress)

    progress("Fetching Ventoy's published checksum ...")
    expected = parse_sha256sums(fetch_url_text(release["sha256_url"]), release["zip_name"])
    progress(f"Expected SHA256: {expected}")
    actual = sha256_of_file(zip_path, progress)
    progress(f"Actual SHA256:   {actual}")
    if actual != expected:
        zip_path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded Ventoy zip does NOT match GitHub's published checksum — refusing to use it.")
    progress("Checksum verified.")

    extract_dir = dest_dir / "ventoy" / f"ventoy-{release['version']}"
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.parent.mkdir(parents=True, exist_ok=True)
    progress(f"Extracting to {extract_dir} ...")
    with zipfile.ZipFile(zip_path) as zf:
        # Release zip contains a single top-level ventoy-X.Y.Z/ folder; strip
        # it so files land directly in extract_dir instead of double-nesting.
        names = zf.namelist()
        prefix = names[0].split("/")[0] + "/" if names else ""
        for member in names:
            if not member.startswith(prefix) or member == prefix:
                continue
            rel = member[len(prefix):]
            target = extract_dir / rel
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    zip_path.unlink(missing_ok=True)

    exe = extract_dir / "Ventoy2Disk.exe"
    if not exe.exists():
        raise RuntimeError(f"Ventoy2Disk.exe not found after extracting to {extract_dir}")
    progress("Ventoy ready.")
    return exe


def fetch_official_sha256(version: str, filename: str) -> str:
    """Fetch Debian's own published SHA256SUMS for this release and return the
    hex digest listed for `filename` — the thing we actually compare against,
    never a hash typed/pasted into this codebase by hand."""
    url = official_iso_dir_url(version) + "SHA256SUMS"
    return parse_sha256sums(fetch_url_text(url, timeout=20), filename)


def sha256_of_file(path: Path, progress=None) -> str:
    h = hashlib.sha256()
    total = path.stat().st_size
    read = 0
    last_pct = -1
    with open(path, "rb") as f:
        while True:
            buf = f.read(1024 * 1024)
            if not buf:
                break
            h.update(buf)
            read += len(buf)
            if progress and total:
                pct = int(read * 100 / total)
                if pct != last_pct:
                    progress(f"  hashing {pct}%")
                    last_pct = pct
    return h.hexdigest()


def _rmtree_robust(path: Path, log, attempts: int = 3) -> None:
    """shutil.rmtree that doesn't silently give up. `ignore_errors=True` used
    to mask failures here (read-only files copied off the stick, or a file
    still open in Explorer/an editor/antivirus) — the directory would survive
    partially deleted, and the *next* step (copytree re-creating it) would
    fail with a confusing unrelated-looking WinError 183. This clears
    read-only attributes on the way out and retries a few times before
    surfacing one clear, actionable error."""
    def onerror(func, p, _exc_info):
        try:
            import stat
            os_path = Path(p)
            os_path.chmod(stat.S_IWRITE)
            func(p)
        except Exception:
            pass  # let the retry loop / final raise handle it

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        if not path.exists():
            return
        try:
            shutil.rmtree(path, onerror=onerror)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log(f"  Delete attempt {attempt} failed ({exc}), retrying...")
            time.sleep(1.5)
    raise RuntimeError(
        f"Could not remove {path} after {attempts} attempts ({last_exc}). "
        "Close any File Explorer window, editor, or antivirus scan that might have a file "
        "open on this drive, then try again."
    )


def copy_repo_to(dest_root: Path, log) -> None:
    target = dest_root / "linx-ha-kiosk"
    if target.exists():
        log(f"Removing old {target} ...")
        _rmtree_robust(target, log)

    def ignore(dirpath: str, names: list[str]) -> set[str]:
        return {n for n in names if n in COPY_EXCLUDE_DIRS or n in COPY_EXCLUDE_FILES}

    log(f"Copying project to {target} ...")
    shutil.copytree(ROOT, target, ignore=ignore)
    log("Project copy done.")
    log("Note: credentials.env was NOT copied (contains a plain-text password) —")
    log("copy it onto the stick yourself only if you intend to pre-bake login for this tablet.")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Linx HA Kiosk — USB Installer Builder")
        self.geometry("640x820")
        self.minsize(560, 560)
        self.resizable(True, True)

        self.iso_path = tk.StringVar(value=str(find_default_iso() or ""))
        self.ventoy_path = tk.StringVar(value=str(find_ventoy_exe() or ""))
        self.disks: list[UsbDisk] = []
        self.selected_disk: UsbDisk | None = None
        self.busy = False
        self.iso_verified = False
        self.verify_override = tk.BooleanVar(value=False)

        self._build_ui()
        self.refresh_disks()

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 5}

        frm_iso = ttk.LabelFrame(self, text="1. Debian netinst ISO")
        frm_iso.pack(fill="x", **pad)
        row1 = ttk.Frame(frm_iso)
        row1.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Entry(row1, textvariable=self.iso_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row1, text="Browse…", command=self.browse_iso).pack(side="left", padx=(6, 0))
        row2 = ttk.Frame(frm_iso)
        row2.pack(fill="x", padx=6, pady=(2, 2))
        ttk.Button(row2, text="Download latest (verified)", command=self.start_download).pack(side="left")
        ttk.Button(row2, text="Verify checksum", command=self.start_verify).pack(side="left", padx=(6, 0))
        self.verify_status = ttk.Label(row2, text="Not verified yet.", foreground="#a56a1c")
        self.verify_status.pack(side="left", padx=8)
        ttk.Checkbutton(
            frm_iso, variable=self.verify_override, text="Skip verification (offline)",
        ).pack(anchor="w", padx=6, pady=(0, 6))

        frm_ventoy = ttk.LabelFrame(self, text="2. Ventoy2Disk.exe")
        frm_ventoy.pack(fill="x", **pad)
        vrow1 = ttk.Frame(frm_ventoy)
        vrow1.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Entry(vrow1, textvariable=self.ventoy_path).pack(side="left", fill="x", expand=True)
        ttk.Button(vrow1, text="Browse…", command=self.browse_ventoy).pack(side="left", padx=(6, 0))
        vrow2 = ttk.Frame(frm_ventoy)
        vrow2.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(vrow2, text="Download latest Ventoy", command=self.start_download_ventoy).pack(side="left")
        ttk.Button(vrow2, text="ventoy.net (manual)", command=lambda: webbrowser.open(VENTOY_URL)).pack(side="left", padx=(6, 0))

        frm_disk = ttk.LabelFrame(self, text="3. Choose the USB drive to erase")
        frm_disk.pack(fill="both", expand=True, **pad)
        list_row = ttk.Frame(frm_disk)
        list_row.pack(fill="both", expand=True, padx=6, pady=6)
        self.disk_list = tk.Listbox(list_row, height=5, exportselection=False)
        self.disk_list.pack(side="left", fill="both", expand=True)
        self.disk_list.bind("<<ListboxSelect>>", self.on_select_disk)
        ttk.Button(frm_disk, text="Rescan", command=self.refresh_disks).pack(pady=(0, 6))

        frm_confirm = ttk.LabelFrame(self, text="4. Confirm")
        frm_confirm.pack(fill="x", **pad)
        self.warn_label = ttk.Label(frm_confirm, text="Select a drive above.", foreground="#a56a1c", wraplength=580, justify="left")
        self.warn_label.pack(anchor="w", padx=6, pady=6)

        self.go_btn = ttk.Button(self, text="Erase, flash & build installer USB", command=self.start_flash)
        self.go_btn.pack(pady=(4, 4))

        frm_update = ttk.LabelFrame(self, text="5. Or: update linx-ha-kiosk/ on an existing stick")
        frm_update.pack(fill="x", **pad)
        ttk.Label(
            frm_update,
            text="Refreshes just the project folder on the drive selected above — leaves the ISO and Ventoy config untouched.",
            foreground="#555", wraplength=580, justify="left",
        ).pack(anchor="w", padx=6, pady=(6, 4))
        self.update_btn = ttk.Button(
            frm_update, text="Update linx-ha-kiosk/ only", command=self.start_update_project,
        )
        self.update_btn.pack(padx=6, pady=(0, 6))

        self.log_box = tk.Text(self, height=18, state="disabled", bg="#10141a", fg="#eef1f4")
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def log(self, msg: str) -> None:
        def _write():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _write)

    def browse_iso(self) -> None:
        p = filedialog.askopenfilename(title="Select Debian ISO", filetypes=[("ISO image", "*.iso")])
        if p:
            self.iso_path.set(p)
            self._mark_unverified()

    def browse_ventoy(self) -> None:
        p = filedialog.askopenfilename(title="Select Ventoy2Disk.exe", filetypes=[("Ventoy2Disk.exe", "Ventoy2Disk.exe")])
        if p:
            self.ventoy_path.set(p)

    def _mark_unverified(self) -> None:
        self.iso_verified = False
        self.verify_status.configure(text="Not verified yet.", foreground="#a56a1c")

    def start_download(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.go_btn.configure(state="disabled")
        self.update_btn.configure(state="disabled")
        self._mark_unverified()

        def worker():
            try:
                dest, version = download_latest_debian(DOWNLOADS, self.log)
                self.iso_verified = True
                self.after(0, lambda: self.iso_path.set(str(dest)))
                self.after(0, lambda: self.verify_status.configure(text=f"Verified ✓ Debian {version}", foreground="#3dbe7a"))
                self.log(f"Saved to {dest}")
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.log(f"ERROR: {msg}")
                self.after(0, lambda: messagebox.showerror("Download failed", msg))
            finally:
                self.busy = False
                self.after(0, lambda: self.go_btn.configure(state="normal"))
                self.after(0, lambda: self.update_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def start_download_ventoy(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.go_btn.configure(state="disabled")
        self.update_btn.configure(state="disabled")

        def worker():
            try:
                exe = download_and_verify_ventoy(DOWNLOADS, self.log)
                self.after(0, lambda: self.ventoy_path.set(str(exe)))
                self.log(f"Ventoy ready at {exe}")
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.log(f"ERROR: {msg}")
                self.after(0, lambda: messagebox.showerror("Ventoy download failed", msg))
            finally:
                self.busy = False
                self.after(0, lambda: self.go_btn.configure(state="normal"))
                self.after(0, lambda: self.update_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def start_verify(self) -> None:
        if self.busy:
            return
        iso = Path(self.iso_path.get().strip())
        if not iso.exists():
            messagebox.showerror("Missing ISO", "Pick or download a Debian ISO first.")
            return
        version = version_from_iso_filename(iso.name)
        if not version:
            messagebox.showerror(
                "Can't determine version",
                f"'{iso.name}' isn't a standard debian-X.Y.Z-amd64-netinst.iso filename — "
                "can't look up which checksum to check it against.",
            )
            return
        self.busy = True
        self.go_btn.configure(state="disabled")
        self.update_btn.configure(state="disabled")
        self.verify_status.configure(text="Verifying…", foreground="#9aa3ad")

        def worker():
            try:
                self.log(f"Fetching official checksum for Debian {version} ...")
                expected = fetch_official_sha256(version, official_iso_filename(version))
                self.log(f"Official SHA256: {expected}")
                self.log(f"Hashing {iso.name} ...")
                actual = sha256_of_file(iso, self.log)
                self.log(f"Local SHA256:    {actual}")
                ok = actual == expected
                self.iso_verified = ok
                if ok:
                    self.log("MATCH — this ISO is byte-for-byte what Debian published.")
                    self.after(0, lambda: self.verify_status.configure(text="Verified ✓ matches official checksum", foreground="#3dbe7a"))
                else:
                    self.log("MISMATCH — do not use this file.")
                    self.after(0, lambda: self.verify_status.configure(text="MISMATCH — do not use this file", foreground="#c0392b"))
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                self.iso_verified = False
                self.log(f"ERROR: {msg}")
                self.after(0, lambda: self.verify_status.configure(text="Verification failed (see log)", foreground="#c0392b"))
                self.after(0, lambda: messagebox.showerror("Verification failed", msg))
            finally:
                self.busy = False
                self.after(0, lambda: self.go_btn.configure(state="normal"))
                self.after(0, lambda: self.update_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_disks(self) -> None:
        self.disk_list.delete(0, "end")
        self.selected_disk = None
        self.warn_label.configure(text="Select a drive above.")
        try:
            self.disks = list_usb_disks()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Drive scan failed", str(exc))
            self.disks = []
        if not self.disks:
            self.disk_list.insert("end", "No USB drives detected — plug one in and Rescan.")
            return
        for d in self.disks:
            self.disk_list.insert("end", d.label())

    def on_select_disk(self, _evt=None) -> None:
        sel = self.disk_list.curselection()
        if not sel or not self.disks or sel[0] >= len(self.disks):
            return
        self.selected_disk = self.disks[sel[0]]
        d = self.selected_disk
        self.warn_label.configure(
            text=f"⚠ This will ERASE ALL DATA on Disk {d.number}: {d.friendly_name} "
                 f"({d.size_gb} GB, currently {d.drive_letters or 'no drive letter'}). "
                 "This cannot be undone."
        )

    def start_flash(self) -> None:
        if self.busy:
            return
        iso = Path(self.iso_path.get().strip())
        ventoy = Path(self.ventoy_path.get().strip())
        if not iso.exists():
            messagebox.showerror("Missing ISO", "Pick a valid Debian ISO file first.")
            return
        if not self.iso_verified and not self.verify_override.get():
            messagebox.showerror(
                "ISO not verified",
                "Click 'Verify checksum' first, or tick 'Skip verification' if you're offline.",
            )
            return
        if not ventoy.exists() or ventoy.name.lower() != "ventoy2disk.exe":
            messagebox.showerror("Missing Ventoy", "Pick a valid Ventoy2Disk.exe first (download Ventoy if needed).")
            return
        if self.selected_disk is None:
            messagebox.showerror("No drive selected", "Select a USB drive to flash.")
            return
        d = self.selected_disk
        if not messagebox.askyesno(
            "Final confirmation",
            f"Erase Disk {d.number} ({d.friendly_name}, {d.size_gb} GB"
            f"{f', currently {d.drive_letters}' if d.drive_letters else ''}) and build the installer USB?"
            "\n\nThis cannot be undone.",
        ):
            return

        self.busy = True
        self.go_btn.configure(state="disabled")
        self.update_btn.configure(state="disabled")
        threading.Thread(target=self._flash_worker, args=(iso, ventoy, d), daemon=True).start()

    def _flash_worker(self, iso: Path, ventoy: Path, disk: UsbDisk) -> None:
        try:
            self.log(f"Flashing Ventoy onto Disk {disk.number} ...")
            cmd = [str(ventoy), "VTOYCLI", "/I", f"/PhyDrive:{disk.number}", "/GPT", "/NOSB", "/FS:FAT32", "/Y"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            self.log(r.stdout.strip())
            if r.returncode != 0:
                self.log(r.stderr.strip())
                raise RuntimeError(f"Ventoy2Disk exited with code {r.returncode}")
            self.log("Ventoy flashed. Waiting for the new drive letter ...")

            letter = find_data_partition_letter(disk.number)
            self.log(f"Ventoy data partition mounted at {letter}")
            dest = Path(letter + "\\")

            # Fixed filename — ventoy/ventoy.json's conf_replace rules match this
            # exact name so they apply regardless of Debian's own version string.
            self.log(f"Copying {iso.name} as {FIXED_ISO_NAME} ({iso.stat().st_size // (1024*1024)} MB) ...")
            copy_file_with_progress(iso, dest / FIXED_ISO_NAME, self.log)
            self.log("ISO copied (unmodified — verify anytime with the checksum tool above).")

            ventoy_src = ROOT / "ventoy"
            if ventoy_src.exists():
                ventoy_dst = dest / "ventoy"
                if ventoy_dst.exists():
                    shutil.rmtree(ventoy_dst, ignore_errors=True)
                self.log("Copying ventoy/ (boot-param fixup, applied without modifying the ISO) ...")
                shutil.copytree(ventoy_src, ventoy_dst)

            copy_repo_to(dest, self.log)

            (dest / "START-HERE.txt").write_text(
                "Linx HA Kiosk installer USB\n"
                "============================\n\n"
                f"1. Boot the tablet from this USB, select {FIXED_ISO_NAME} in Ventoy.\n"
                "   (This is the official, unmodified Debian ISO — GPU-crash boot params\n"
                "   are applied by Ventoy at boot time via ventoy/ventoy.json, not baked in.)\n"
                "2. Follow linx-ha-kiosk/docs/INSTALL.md from step 2 (BIOS) onward.\n"
                "3. The linx-ha-kiosk/ folder on this stick has the scripts + firmware you'll need.\n",
                encoding="utf-8",
            )
            self.log("Wrote START-HERE.txt")
            self.log("\nDone. The USB stick is ready to boot on the tablet.")
            self.after(0, lambda: messagebox.showinfo("Done", f"Installer USB ready on drive {letter}"))
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            self.log(f"ERROR: {msg}")
            self.after(0, lambda: messagebox.showerror("Failed", msg))
        finally:
            self.busy = False
            self.after(0, lambda: self.go_btn.configure(state="normal"))
            self.after(0, lambda: self.update_btn.configure(state="normal"))

    def start_update_project(self) -> None:
        if self.busy:
            return
        if self.selected_disk is None:
            messagebox.showerror("No drive selected", "Select a USB drive in step 3 first.")
            return
        d = self.selected_disk
        if not messagebox.askyesno(
            "Update project files",
            f"Replace the linx-ha-kiosk/ folder on Disk {d.number} ({d.friendly_name}) with the current version?\n\n"
            "Everything else on the drive (the ISO, ventoy/) is left untouched.",
        ):
            return

        self.busy = True
        self.go_btn.configure(state="disabled")
        self.update_btn.configure(state="disabled")
        threading.Thread(target=self._update_project_worker, args=(d,), daemon=True).start()

    def _update_project_worker(self, disk: UsbDisk) -> None:
        try:
            self.log(f"Locating data partition on Disk {disk.number} ...")
            letter = find_data_partition_letter(disk.number, timeout=10)
            self.log(f"Found {letter}")
            dest = Path(letter + "\\")
            copy_repo_to(dest, self.log)
            self.log("\nDone. linx-ha-kiosk/ is up to date on this stick.")
            self.after(0, lambda: messagebox.showinfo("Done", f"linx-ha-kiosk/ updated on drive {letter}"))
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            self.log(f"ERROR: {msg}")
            self.after(0, lambda: messagebox.showerror("Failed", msg))
        finally:
            self.busy = False
            self.after(0, lambda: self.go_btn.configure(state="normal"))
            self.after(0, lambda: self.update_btn.configure(state="normal"))


if __name__ == "__main__":
    # Required up front, not offered reactively when a write fails: relaunching
    # elevated starts a brand new process, which used to happen mid-workflow
    # (e.g. right before flashing) and threw away everything already filled
    # in — the ISO/Ventoy paths, the picked drive. Elevating before the first
    # window even opens means that never happens.
    if not is_admin():
        relaunch_as_admin()
        sys.exit(0)
    App().mainloop()
