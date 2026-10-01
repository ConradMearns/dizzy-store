"""Shared builders for the unit tests (the scenarios build their own clusters)."""
import hashlib

import pytest

from dizzy_store.node import StoreNode
from dizzy_store.sim import SimCluster

HOT = {"role": "hot", "wants": []}
ARCHIVE = {"role": "archive", "wants": ["*"]}
COLD = {"role": "cold", "wants": ["*"]}
IDLE = {"role": "archive", "wants": []}          # an archive that fetches only when told


@pytest.fixture(autouse=True)
def not_this_machine(monkeypatch, tmp_path_factory):
    """The tests must not see the machine they run on: not whatever drives are mounted, and not the real
    user's dizzy-store configuration (there is one, and it names a real store)."""
    monkeypatch.setattr("dizzy_store.config._discover", lambda: [])
    nowhere = tmp_path_factory.mktemp("no-user-config")
    monkeypatch.setenv("HOME", str(nowhere))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(nowhere / ".config"))
    for var in ("DIZZY_STORE_CONFIG", "DIZZY_STORE_ROOT", "STORE_ROOT", "DIZZY_STORE_DEVICE", "DIZZY_STORE_HOST"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def cluster_of(tmp_path):
    """``cluster_of(a=card, b=card, ...)``: a cluster of announced devices (the first
    founds it). Each card gets site = its own name unless one is given."""
    built = []

    def build(**nodes):
        cluster = SimCluster(tmp_path / f"cluster-{len(built)}")
        built.append(cluster)
        for index, (name, card) in enumerate(nodes.items()):
            card = {"site": name, **card}
            (cluster.found if index == 0 else cluster.add_node)(name, card)
        for node in cluster.nodes.values():
            node.announce()
        cluster.settle()
        return cluster

    yield build
    for cluster in built:
        cluster.close()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def events_of(node, kind: str, by: str | None = None) -> list[dict]:
    """Payloads of every event of one type in a node's log, oldest first — a log holds
    everyone's facts, so ``by`` keeps only those a given device wrote."""
    return [e.payload for e in node.store.iterate()
            if e.type == kind and (by is None or e.payload.get("node_id") == by)]


def flip(path) -> None:
    """Rot a file in place: same size, first byte flipped."""
    data = bytearray(path.read_bytes())
    data[0] ^= 0xFF
    path.write_bytes(bytes(data))


def sync_both(cluster, a: str, b: str) -> None:
    cluster.nodes[a].run("sync_peer", peer_id=b, direction="both")
    cluster.settle()


def reopen(cluster, node) -> StoreNode:
    """The same device after a restart: same disk, same identity, a fresh process."""
    node.close()
    fresh = StoreNode(node.name, node.root, cluster_id=node.cluster_id, card=node.card,
                      config=node.config, epoch=node.epoch, life=node.life)
    fresh.peers = node.peers
    cluster.nodes[node.name] = fresh
    return fresh


def rebuilt(node) -> bool:
    return any(p.stage == "rebuild" for p in node.progress)


# ── a fake /sys and mountinfo, so storage logic is tested without hardware ───

def make_disk(sysfs, name, *, model="WDC WD20SDRW", vendor="WD", rotational=1, removable=0, size=3906963456,
              bus="usb", usb_speed=5000, parts=("1",), major=8):
    """A whole disk in a fake sysfs, with partitions; returns {partition number: 'major:minor'}."""
    from pathlib import Path
    sysfs = Path(sysfs)
    chain = {"usb": "devices/pci0000:00/0000:00:14.0/usb4/4-2/4-2:1.0/host6/target6:0:0/6:0:0:0/block",
             "nvme": "devices/pci0000:00/0000:00:1d.0/nvme/nvme0/nvme0n1/..",
             "sata": "devices/pci0000:00/0000:00:17.0/ata1/host0/target0:0:0/0:0:0:0/block"}[bus]
    disk = (sysfs / chain / name) if bus != "nvme" else sysfs / "devices/pci0000:00/0000:00:1d.0/nvme/nvme0" / name
    (disk / "queue").mkdir(parents=True)
    (disk / "device").mkdir()
    (disk / "removable").write_text(str(removable))
    (disk / "queue" / "rotational").write_text(str(rotational))
    (disk / "size").write_text(str(size))
    (disk / "device" / "model").write_text(model)
    (disk / "device" / "vendor").write_text(vendor)
    if bus == "usb":
        node = sysfs / "devices/pci0000:00/0000:00:14.0/usb4/4-2"
        (node / "idVendor").write_text("1058")
        (node / "speed").write_text(str(usb_speed))
    (sysfs / "dev" / "block").mkdir(parents=True, exist_ok=True)
    ids = {}
    for i, part in enumerate(parts):
        pdir = disk / f"{name}{part}"
        pdir.mkdir()
        (pdir / "partition").write_text(part)
        link = sysfs / "dev" / "block" / f"{major}:{i + 1}"
        link.symlink_to(pdir)
        ids[part] = f"{major}:{i + 1}"
    return ids


def make_dm(sysfs, name, dev, uuid, slave_dir):
    """A device-mapper node (LUKS or LVM) made of another block device."""
    from pathlib import Path
    sysfs = Path(sysfs)
    node = sysfs / "devices/virtual/block" / name
    (node / "dm").mkdir(parents=True)
    (node / "dm" / "uuid").write_text(uuid)
    (node / "slaves").mkdir()
    (node / "slaves" / Path(slave_dir).name).symlink_to(slave_dir)
    (sysfs / "dev" / "block").mkdir(parents=True, exist_ok=True)
    (sysfs / "dev" / "block" / dev).symlink_to(node)
    return node


def mountinfo_line(mount_id, dev, mountpoint, fstype, source, options="rw,nosuid,nodev,relatime", root="/"):
    return f"{mount_id} 1 {dev} {root} {mountpoint} {options} shared:1 - {fstype} {source} rw,errors=remount-ro"
