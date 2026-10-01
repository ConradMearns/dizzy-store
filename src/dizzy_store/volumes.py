"""What a path physically lives on — read from /proc and /sys, no root needed.

Given a directory: which mount holds it, what filesystem and options, which disk is underneath (through
LVM and dm-crypt if need be), whether that disk spins, is removable, sits behind USB (and at what
speed), is encrypted. `doctor` turns this into advice; `eject` into the commands that unmount and power
off the right thing. Linux only, and every read tolerates a missing file — sysfs differs across kernels,
virtual machines and exotic hardware, and "unknown" is an answer.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_OCTAL = re.compile(r"\\([0-7]{3})")


def _unescape(text: str) -> str:
    """mountinfo writes space, tab, newline and backslash as \\040 \\011 \\012 \\134."""
    return _OCTAL.sub(lambda m: chr(int(m.group(1), 8)), text)


@dataclass(frozen=True)
class Mount:
    mount_id: int
    parent_id: int
    dev: str                  # "major:minor"
    root: str
    mountpoint: str
    options: str
    fstype: str
    source: str
    super_options: str


def parse_mountinfo(text: str) -> list[Mount]:
    """/proc/self/mountinfo: ``36 35 98:0 /root /mnt rw,noatime shared:1 - ext4 /dev/sda1 rw,errors=x``."""
    mounts = []
    for line in text.splitlines():
        left, sep, right = line.partition(" - ")
        fields = left.split()
        if not sep or len(fields) < 6:
            continue
        rest = right.split(" ", 2)
        if len(rest) < 3:
            continue
        mounts.append(Mount(int(fields[0]), int(fields[1]), fields[2], _unescape(fields[3]),
                            _unescape(fields[4]), fields[5], rest[0], _unescape(rest[1]), rest[2]))
    return mounts


def read_mounts(path: str = "/proc/self/mountinfo") -> list[Mount]:
    try:
        return parse_mountinfo(Path(path).read_text())
    except OSError:
        return []


def mount_for(path: str | Path, mounts: Optional[list[Mount]] = None) -> Optional[Mount]:
    """The mount a path lives on: the one with the longest mountpoint that contains it (the latest wins
    when mounts are stacked at one point)."""
    mounts = read_mounts() if mounts is None else mounts
    real = os.path.realpath(path)
    best: Optional[Mount] = None
    for m in mounts:
        mp = m.mountpoint.rstrip("/") or "/"
        inside = real == mp or mp == "/" or real.startswith(mp + "/")
        if inside and (best is None or len(m.mountpoint) >= len(best.mountpoint)):
            best = m
    return best


@dataclass
class Disk:
    name: str                                   # sda, nvme0n1
    model: str = ""
    removable: bool = False
    rotational: Optional[bool] = None
    transport: str = ""                         # usb | nvme | sata | virtio | ""
    usb_mbps: Optional[int] = None              # the negotiated link speed (480, 5000, 10000)
    size_bytes: int = 0


@dataclass
class Placement:
    """Everything known about where a path lives."""
    mount: Optional[Mount]
    disks: list[Disk] = field(default_factory=list)         # the physical disk(s) underneath
    encrypted: bool = False                                  # dm-crypt / LUKS somewhere below
    lvm: bool = False
    layers: list[str] = field(default_factory=list)          # e.g. ["partition", "dm-crypt", "lvm"]

    @property
    def disk(self) -> Optional[Disk]:
        return self.disks[0] if self.disks else None


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _disk_from(dirpath: Path) -> Disk:
    """A whole-disk sysfs directory (.../block/sda) -> Disk."""
    rotational = _read(dirpath / "queue" / "rotational")
    real = str(dirpath.resolve())
    transport = ("usb" if "/usb" in real else "nvme" if "/nvme" in real else
                 "virtio" if "/virtio" in real else "sata" if "/ata" in real else "")
    speed = None
    if transport == "usb":                       # climb to the USB device node, which carries `speed`
        for parent in dirpath.resolve().parents:
            if (parent / "idVendor").exists() and (parent / "speed").exists():
                digits = _read(parent / "speed")
                speed = int(float(digits)) if digits.replace(".", "", 1).isdigit() else None
                break
    size = _read(dirpath / "size")
    return Disk(name=dirpath.name,
                model=" ".join(x for x in (_read(dirpath / "device" / "vendor"), _read(dirpath / "device" / "model")) if x),
                removable=_read(dirpath / "removable") == "1",
                rotational=None if rotational == "" else rotational == "1",
                transport=transport, usb_mbps=speed,
                size_bytes=int(size) * 512 if size.isdigit() else 0)


def placement_for(mount: Optional[Mount], sysfs: str | Path = "/sys") -> Placement:
    """Follow a mount's block device down through partitions, LVM and dm-crypt to the physical disk."""
    if mount is None:
        return Placement(None)
    out = Placement(mount)
    start = Path(sysfs) / "dev" / "block" / mount.dev
    if not start.exists():
        return out                               # a tmpfs, a network mount: no block device under it
    seen: set[Path] = set()

    def walk(node: Path) -> None:
        node = node.resolve()
        if node in seen:
            return
        seen.add(node)
        if (node / "dm").is_dir():               # device-mapper: LUKS, LVM — look at what it is made of
            uuid = _read(node / "dm" / "uuid")
            if uuid.startswith("CRYPT-"):
                out.encrypted = True
                out.layers.append("dm-crypt")
            elif uuid.startswith("LVM-"):
                out.lvm = True
                out.layers.append("lvm")
            else:
                out.layers.append("device-mapper")
            for slave in sorted((node / "slaves").glob("*")):
                walk(slave)
            return
        if (node / "partition").exists():        # a partition: its parent directory is the disk
            out.layers.append("partition")
            walk(node.parent)
            return
        out.disks.append(_disk_from(node))

    walk(start)
    return out


def describe(path: str | Path, mounts: Optional[list[Mount]] = None, sysfs: str | Path = "/sys") -> Placement:
    return placement_for(mount_for(path, mounts), sysfs)


def same_filesystem(a: str | Path, b: str | Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False
