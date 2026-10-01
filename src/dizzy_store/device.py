"""A device's on-disk identity and state: <root>/.store/device.json.

What makes a device portable lives under its root — plug a drive in, cd into it, run the
tool. The file holds the device's identity (node_id, a random epoch generated when the state
is created, the cluster it belongs to), its public card (role, site, what it wants) and its two
secrets. It is mode 0600: it carries tokens.

How a MACHINE runs the device — listen address, announced endpoints, seeds, cadence, limits,
pacing — is the machine's configuration (config.py). ``Device`` overlays those settings on the
persisted state as a read-only view: ``device["listen"]`` is what is in force, ``device.data`` is
what is on the drive, and ``save()`` writes only the latter, so a setting that belongs to this
computer never gets baked into a drive that will be plugged into another.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
from pathlib import Path
from typing import Any, Optional

from .config import DeviceSettings
from .node import StoreNode
from storeutil import NotAStore

DEFAULT_INTERVALS = {"sync_s": 30, "sweep_s": 60, "capacity_s": 60,
                     "access_s": 60, "scrub_s": 86400}


def device_file(root: str | Path) -> Path:
    return Path(root) / ".store" / "device.json"


def current_host() -> str:
    """Which computer is this? A drive remembers things that are only true on the machine that learned
    them (a listen port, a tunnel to a peer) under that machine's name. $DIZZY_STORE_HOST overrides the
    hostname — for a machine whose name changes, and for testing "another computer" on this one."""
    return os.environ.get("DIZZY_STORE_HOST") or socket.gethostname()


class Device:
    def __init__(self, root: Path, data: dict[str, Any], settings: Optional[DeviceSettings] = None):
        self.root = Path(root)
        self.data = data                         # what is on the drive
        self.settings = settings or DeviceSettings()   # what this machine says about running it

    # ── persistence ──────────────────────────────────────────────────────────

    @classmethod
    def exists(cls, root: str | Path) -> bool:
        return device_file(root).is_file()

    @classmethod
    def load(cls, root: str | Path, settings: Optional[DeviceSettings] = None) -> "Device":
        path = device_file(root)
        if not path.is_file():
            raise NotAStore(f"{root} is not a store device (no {path}) — run `init` first, "
                            "or check that its drive is mounted")
        return cls(Path(root), json.loads(path.read_text()), settings)

    @classmethod
    def init(cls, root: str | Path, *, node_id: str, role: str, site: str,
             wants: Optional[list[str]] = None, location_note: Optional[str] = None,
             listen: Optional[str] = None, endpoints: Optional[list[str]] = None,
             seeds: Optional[dict[str, str]] = None, peer_token: Optional[str] = None,
             config: Optional[dict[str, Any]] = None) -> "Device":
        if cls.exists(root):
            raise FileExistsError(f"{root} is already a store device")
        data = {
            "node_id": node_id,
            "epoch": secrets.token_hex(8),            # this LIFE of the device (principle 4)
            "cluster_id": None,
            "role": role, "site": site, "location_note": location_note,
            "wants": list(wants or []), "draining": False,
            "endpoints": [], "listen": "127.0.0.1:7700", "seeds": {},     # defaults for any host with no entry
            "hosts": {},                                 # what THIS machine knows: listen, endpoints, seeds
            "peer_token": peer_token or secrets.token_urlsafe(24),
            "admin_token": secrets.token_urlsafe(24),  # local only: never shared
            "config": dict(config or {}),
            "intervals": dict(DEFAULT_INTERVALS),
        }
        device = cls(Path(root), data)
        for key, value in (("listen", listen), ("endpoints", endpoints), ("seeds", seeds)):
            if value:
                device.remember(key, value)              # said at init: true HERE, not on every machine
        device.save()
        return device

    def save(self) -> None:
        path = device_file(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)

    # ── what this machine knows ──────────────────────────────────────────────

    @property
    def host(self) -> dict[str, Any]:
        """What the drive remembers about THIS computer (listen, endpoints, seeds), if it has been here."""
        return self.data.get("hosts", {}).get(current_host(), {})

    def remember(self, key: str, value: Any) -> None:
        """Record something that is true on this computer only, under this computer's name."""
        self.data.setdefault("hosts", {}).setdefault(current_host(), {})[key] = value

    def remember_seed(self, name: str, url: str) -> None:
        seeds = dict(self.host.get("seeds", {}))
        seeds[name] = url
        self.remember("seeds", seeds)

    # ── views ────────────────────────────────────────────────────────────────

    def __getitem__(self, key: str) -> Any:
        """The value IN FORCE: this machine's config over what the drive remembers of this machine over
        the drive's generic defaults."""
        d, s, h = self.data, self.settings, self.host
        if key == "listen":
            return s.listen or h.get("listen") or d["listen"]
        if key == "endpoints":
            if s.endpoints is not None:
                return list(s.endpoints)
            return list(h["endpoints"]) if "endpoints" in h else list(d["endpoints"])
        if key == "seeds":
            return {**d["seeds"], **h.get("seeds", {}), **(s.seeds or {})}
        if key == "site":
            return s.site or d["site"]
        if key == "location_note":
            return s.location_note if s.location_note is not None else d.get("location_note")
        if key == "intervals":
            return {**d["intervals"], **(s.intervals or {})}
        if key == "config":
            return {**(d.get("config") or {}), **s.env_store()}
        return d[key]

    @property
    def card(self) -> dict[str, Any]:
        d = self.data
        return {"role": d["role"], "site": self["site"], "location_note": self["location_note"],
                "wants": d["wants"], "draining": d.get("draining", False),
                "endpoints": self["endpoints"]}

    @property
    def host_port(self) -> tuple[str, int]:
        host, _, port = self["listen"].rpartition(":")
        return host or "127.0.0.1", int(port)

    def build_node(self) -> StoreNode:
        """The device as a running StoreNode (no transport attached yet)."""
        d = self.data
        return StoreNode(d["node_id"], self.root, cluster_id=d.get("cluster_id"),
                         card=self.card, config=self["config"], epoch=d["epoch"],
                         create_root=False)
