"""Finding the stores on the drives that are plugged in right now.

A portable drive carries its own identity under <mount>/dizzy-store/.store/, and the same drive is
mounted at a different path on every computer (and under a different user's name). So nothing about
where it is belongs in a configuration: this looks at what is mounted and reads what each drive says
about itself. `dizzy-store -d NAME` falls back to it when NAME is not a configured device, and
`dizzy-store drives` lists what it found.

Only local block-device mounts are looked at (never the system volume, never a network mount that could
hang), and each costs two `stat`s.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import volumes

STORE_DIRNAME = "dizzy-store"      # where a store lives on a drive: <mount>/dizzy-store


@dataclass(frozen=True)
class FoundStore:
    root: Path
    node_id: str
    role: str
    site: str
    cluster_id: Optional[str]
    mountpoint: str
    source: str


def find_stores(mounts: Optional[list[volumes.Mount]] = None) -> list[FoundStore]:
    """Every store carried by a mounted drive: in the conventional `dizzy-store/` folder, or at the
    drive's top (a drive dedicated to the store)."""
    mounts = volumes.read_mounts() if mounts is None else mounts
    seen: set[Path] = set()
    found: list[FoundStore] = []
    for mount in mounts:
        if mount.mountpoint == "/" or not mount.source.startswith("/dev/"):
            continue
        top = Path(mount.mountpoint)
        for candidate in (top / STORE_DIRNAME, top):
            try:
                data = json.loads((candidate / ".store" / "device.json").read_text())
            except (OSError, ValueError):
                continue
            if candidate in seen or not isinstance(data, dict):
                continue
            seen.add(candidate)
            found.append(FoundStore(candidate, str(data.get("node_id", "?")), str(data.get("role", "?")),
                                    str(data.get("site", "?")), data.get("cluster_id"), mount.mountpoint,
                                    mount.source))
    return sorted(found, key=lambda f: (f.node_id, str(f.root)))
