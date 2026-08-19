#!/usr/bin/env python3
"""Rebuild a Ventoy-bootable Debian netinst ISO with Linx firmware injected."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pycdlib

ROOT = Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
DL = ROOT / "downloads"
ISO_IN = DL / "debian-13.6.0-amd64-netinst.iso"
ISO_OUT = DL / "debian-13.6.0-amd64-netinst-linxfw.iso"
ISO_ROOT = DL / "iso-work" / "iso-root"
FW = ROOT / "firmware-media" / "firmware" / "brcm"


def main() -> int:
    if not ISO_ROOT.exists():
        print("Missing extracted ISO tree", file=sys.stderr)
        return 1

    # Ensure loose firmware files exist in tree
    dest_fw = ISO_ROOT / "firmware" / "brcm"
    dest_fw.mkdir(parents=True, exist_ok=True)
    for p in FW.iterdir():
        if p.is_file():
            shutil.copy2(p, dest_fw / p.name)

    print("Creating ISO from directory via pycdlib (Joliet + Rock Ridge)...")
    iso = pycdlib.PyCdlib()
    iso.new(joliet=3, rock_ridge="1.09", vol_ident="DEBIAN 13.6.0 LINX")

    def add_dir(fs_path: Path, iso_path: str, joliet_path: str, rr_name: str | None = None):
        # iso_path like /FOO/BAR ; joliet like /foo/bar
        if iso_path != "/":
            iso.add_directory(iso_path, rr_name=rr_name or fs_path.name, joliet_path=joliet_path)
        for child in sorted(fs_path.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            if child.name == "[BOOT]":
                continue
            name = child.name
            # ISO9660 identifier
            iso_id = name.upper()
            if child.is_dir():
                child_iso = (iso_path.rstrip("/") + "/" + iso_id).replace("//", "/")
                child_joliet = (joliet_path.rstrip("/") + "/" + name).replace("//", "/")
                add_dir(child, child_iso if child_iso != "/" else "/" + iso_id, child_joliet, rr_name=name)
            else:
                # file
                iso_file = (iso_path.rstrip("/") + "/" + iso_id + ";1").replace("//", "/")
                joliet_file = (joliet_path.rstrip("/") + "/" + name).replace("//", "/")
                # Fix ISO9660: replace invalid chars, truncate
                # pycdlib wants proper format - use rr_name for real name
                try:
                    iso.add_file(
                        str(child),
                        iso_path=iso_file,
                        rr_name=name,
                        joliet_path=joliet_file,
                    )
                except Exception:
                    # Fallback: force a safe ISO name
                    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name.upper())
                    if "." in safe:
                        base, ext = safe.rsplit(".", 1)
                        safe = f"{base[:8]}.{ext[:3]}"
                    else:
                        safe = safe[:11]
                    iso_file = (iso_path.rstrip("/") + "/" + safe + ";1").replace("//", "/")
                    iso.add_file(
                        str(child),
                        iso_path=iso_file,
                        rr_name=name,
                        joliet_path=joliet_file,
                    )

    # Manually walk adding directories/files with safer naming using pycdlib helper if available
    # Use add_fp style via walk
    for dirpath, dirnames, filenames in __import__("os").walk(ISO_ROOT):
        dirnames[:] = [d for d in dirnames if d != "[BOOT]"]
        rel = Path(dirpath).relative_to(ISO_ROOT)
        if rel.parts:
            # create directory chain
            joliet = "/" + "/".join(rel.parts)
            # build iso9660 path
            iso_parts = []
            for part in rel.parts:
                p = part.upper()
                p = "".join(c if c.isalnum() or c in "._-" else "_" for c in p)
                if len(p) > 31:
                    p = p[:31]
                iso_parts.append(p)
            iso_p = "/" + "/".join(iso_parts)
            try:
                iso.add_directory(iso_path=iso_p, rr_name=rel.parts[-1], joliet_path=joliet)
            except Exception as e:
                # may already exist
                if "exists" not in str(e).lower() and "already" not in str(e).lower():
                    pass

        for fn in filenames:
            full = Path(dirpath) / fn
            rel_file = full.relative_to(ISO_ROOT)
            joliet = "/" + "/".join(rel_file.parts)
            iso_parts = []
            for part in rel_file.parts[:-1]:
                p = part.upper()
                p = "".join(c if c.isalnum() or c in "._-" else "_" for c in p)[:31]
                iso_parts.append(p)
            fname = rel_file.parts[-1]
            safe = fname.upper()
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in safe)
            if "." in safe:
                base, ext = safe.rsplit(".", 1)
                safe_name = f"{base[:8]}.{ext[:3]}"
            else:
                safe_name = safe[:11]
            iso_file = ("/" + "/".join(iso_parts + [safe_name])).replace("//", "/") + ";1"
            try:
                iso.add_file(str(full), iso_path=iso_file, rr_name=fname, joliet_path=joliet)
            except Exception as e:
                print("skip", joliet, e)

    if ISO_OUT.exists():
        ISO_OUT.unlink()
    print(f"Writing {ISO_OUT} ...")
    iso.write(str(ISO_OUT))
    iso.close()
    print(f"Done: {ISO_OUT} ({ISO_OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
