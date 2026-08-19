#!/usr/bin/env python3
"""Inject Linx Broadcom firmware into an existing Debian netinst ISO (preserve boot)."""
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


def find_record(iso: pycdlib.PyCdlib, joliet_path: str):
    try:
        return iso.get_record(joliet_path=joliet_path)
    except Exception:
        return None


def main() -> int:
    patched_initrd = ISO_ROOT / "install.amd" / "initrd.gz"
    patched_gtk = ISO_ROOT / "install.amd" / "gtk" / "initrd.gz"
    if not patched_initrd.exists():
        print("Patched initrd missing — run extract/inject first", file=sys.stderr)
        return 1

    print(f"Opening {ISO_IN}")
    iso = pycdlib.PyCdlib()
    iso.open(str(ISO_IN))
    print(
        "joliet=",
        iso.has_joliet(),
        " rr=",
        iso.has_rock_ridge(),
        " udf=",
        iso.has_udf(),
    )

    # Show how initrd is named in the ISO
    for p in ("/install.amd", "/install.amd/gtk", "/firmware"):
        print("list", p)
        try:
            for c in iso.list_children(joliet_path=p):
                name = c.file_identifier()
                if hasattr(c, "rock_ridge") and c.rock_ridge is not None:
                    try:
                        name = c.rock_ridge.name()
                    except Exception:
                        pass
                print(" ", name)
        except Exception as e:
            print("  ERR", e)

    replacements = [
        ("/install.amd/initrd.gz", patched_initrd),
        ("/install.amd/gtk/initrd.gz", patched_gtk),
    ]

    for jpath, src in replacements:
        if not src.exists():
            print("skip missing", src)
            continue
        print(f"Replace {jpath} with {src} ({src.stat().st_size} bytes)")
        # Remove existing (try joliet + iso_path variants)
        removed = False
        for kwargs in (
            {"joliet_path": jpath},
            {"iso_path": jpath.upper() + ";1"},
            {"rr_path": jpath},
        ):
            try:
                iso.rm_file(**kwargs)
                print("  removed via", kwargs)
                removed = True
                break
            except Exception as e:
                print("  rm fail", kwargs, e)
        if not removed:
            print("WARNING: could not remove", jpath)

        # Add new file
        iso_name = Path(jpath).name.upper()
        if "." in iso_name:
            base, ext = iso_name.rsplit(".", 1)
            iso_id = f"{base[:8]}.{ext[:3]};1"
        else:
            iso_id = iso_name[:11] + ";1"
        parent = str(Path(jpath).parent).replace("\\", "/")
        iso_path = f"{parent.upper()}/{iso_id}".replace("//", "/")
        if not iso_path.startswith("/"):
            iso_path = "/" + iso_path
        # Fix INSTALL.AMD style
        parts = [p for p in parent.split("/") if p]
        iso_parts = []
        for p in parts:
            up = p.upper()
            up = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in up)[:31]
            iso_parts.append(up)
        iso_path = "/" + "/".join(iso_parts + [iso_id])

        added = False
        for kwargs in (
            {
                "iso_path": iso_path,
                "rr_name": Path(jpath).name,
                "joliet_path": jpath,
            },
            {"joliet_path": jpath, "rr_name": Path(jpath).name},
        ):
            try:
                iso.add_file(str(src), **kwargs)
                print("  added via", kwargs)
                added = True
                break
            except Exception as e:
                print("  add fail", e)
        if not added:
            print("ERROR adding", jpath, file=sys.stderr)
            iso.close()
            return 1

    # Ensure /firmware/brcm exists and add files
    # Create directory if needed
    for dpath in ("/firmware/brcm",):
        try:
            iso.add_directory(
                iso_path="/FIRMWARE/BRCM",
                rr_name="brcm",
                joliet_path=dpath,
            )
            print("created", dpath)
        except Exception as e:
            print("mkdir", dpath, e)

    for src in sorted(FW.iterdir()):
        if not src.is_file():
            continue
        jpath = f"/firmware/brcm/{src.name}"
        # remove if present
        for kwargs in ({"joliet_path": jpath},):
            try:
                iso.rm_file(**kwargs)
            except Exception:
                pass
        safe = src.name.upper()
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in safe)
        if "." in safe:
            base, ext = safe.rsplit(".", 1)
            iso_id = f"{base[:8]}.{ext[:3]};1"
        else:
            iso_id = safe[:11] + ";1"
        iso_path = f"/FIRMWARE/BRCM/{iso_id}"
        try:
            iso.add_file(
                str(src),
                iso_path=iso_path,
                rr_name=src.name,
                joliet_path=jpath,
            )
            print("added", jpath)
        except Exception as e:
            print("failed", jpath, e)

    if ISO_OUT.exists():
        ISO_OUT.unlink()
    print(f"Writing {ISO_OUT}")
    iso.write(str(ISO_OUT))
    iso.close()
    print(f"Done ({ISO_OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
