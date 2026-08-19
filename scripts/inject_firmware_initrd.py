#!/usr/bin/env python3
"""Append Broadcom firmware to a Debian installer initrd.gz (concatenated gzip cpio)."""
from __future__ import annotations

import gzip
import io
import os
import stat
import struct
import sys
from pathlib import Path


def align4(n: int) -> int:
    return (n + 3) & ~3


def cpio_header(name: str, mode: int, size: int, ino: int) -> bytes:
    # newc header, 110 bytes hex fields + name + NUL, padded to 4 bytes
    name_b = name.encode("ascii") + b"\0"
    hdr = (
        b"070701"
        + f"{ino:08x}".encode()
        + f"{mode:08x}".encode()
        + b"00000000"  # uid
        + b"00000000"  # gid
        + b"00000001"  # nlink
        + b"00000000"  # mtime
        + f"{size:08x}".encode()
        + b"00000000"  # major
        + b"00000000"  # minor
        + b"00000000"  # rmajor
        + b"00000000"  # rminor
        + f"{len(name_b):08x}".encode()
        + b"00000000"  # checksum
    )
    assert len(hdr) == 110
    pad = b"\0" * (align4(110 + len(name_b)) - (110 + len(name_b)))
    return hdr + name_b + pad


def build_firmware_cpio(files: dict[str, bytes]) -> bytes:
    """files: archive path (no leading slash) -> content"""
    out = io.BytesIO()
    ino = 1
    # directories first
    dirs = sorted({str(Path(p).parent).replace("\\", "/") for p in files} | {".", "lib", "lib/firmware", "lib/firmware/brcm"})
    dirs = [d for d in dirs if d and d != "."]
    # ensure unique ordered parents
    all_dirs = []
    seen = set()
    for d in sorted(dirs, key=lambda s: (s.count("/"), s)):
        parts = d.split("/")
        cur = []
        for part in parts:
            cur.append(part)
            path = "/".join(cur)
            if path not in seen:
                seen.add(path)
                all_dirs.append(path)

    for d in all_dirs:
        ino += 1
        mode = stat.S_IFDIR | 0o755
        hdr = cpio_header(d, mode, 0, ino)
        out.write(hdr)

    for name, data in sorted(files.items()):
        ino += 1
        mode = stat.S_IFREG | 0o644
        hdr = cpio_header(name.replace("\\", "/"), mode, len(data), ino)
        out.write(hdr)
        out.write(data)
        out.write(b"\0" * (align4(len(data)) - len(data)))

    # TRAILER
    ino += 1
    out.write(cpio_header("TRAILER!!!", 0, 0, ino))
    # pad archive end
    pos = out.tell()
    out.write(b"\0" * (align4(pos) - pos))
    return out.getvalue()


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: inject_firmware_initrd.py <initrd.gz> <firmware-brcm-dir> [output.initrd.gz]", file=sys.stderr)
        return 2
    initrd_path = Path(sys.argv[1])
    fw_dir = Path(sys.argv[2])
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else initrd_path

    files: dict[str, bytes] = {}
    for p in fw_dir.iterdir():
        if p.is_file():
            files[f"lib/firmware/brcm/{p.name}"] = p.read_bytes()
    if not files:
        print("No firmware files found", file=sys.stderr)
        return 1

    cpio = build_firmware_cpio(files)
    fw_gz = gzip.compress(cpio, compresslevel=9, mtime=0)
    original = initrd_path.read_bytes()
    out_path.write_bytes(original + fw_gz)
    print(f"Wrote {out_path} ({out_path.stat().st_size} bytes); appended {len(files)} firmware files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
