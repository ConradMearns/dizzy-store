"""An in-process cluster: devices, a network that can partition, a clock.

The simulation implements the peers client over direct calls, so a scenario
exercises the REAL procedures, projections, queries, policies and DAG
replication — only the transport (and the passage of time) is simulated.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator, Optional

from .node import PeerSurface, StoreNode
from storeutil import PeerUnreachable


class SimPeers:
    """The peers client one device holds: calls reach another device only if the
    network lets them (offline / partitioned -> PeerUnreachable)."""

    def __init__(self, cluster: "SimCluster", me: str):
        self._cluster, self._me = cluster, me

    def _surface(self, peer_id: str) -> PeerSurface:
        return self._cluster.surface(self._me, peer_id)

    def cluster_id(self, peer_id: str) -> Optional[str]:
        return self._surface(peer_id).cluster_id()

    def pull_from(self, peer_id: str) -> int:
        return self._cluster.nodes[self._me].pull_from_surface(self._surface(peer_id))

    def request_pull(self, peer_id: str) -> None:
        self._surface(peer_id).request_pull(self._me)

    def blob_size(self, peer_id: str, blob_hash: str) -> Optional[int]:
        return self._surface(peer_id).blob_size(blob_hash)

    def verify_blob(self, peer_id: str, blob_hash: str) -> dict:
        return self._surface(peer_id).verify_blob(blob_hash)

    def read_blob(self, peer_id: str, blob_hash: str, offset: int = 0,
                  length: Optional[int] = None) -> Iterator[bytes]:
        return self._surface(peer_id).read_blob(blob_hash, offset, length)


class SimDisk:
    """A filesystem of ``capacity`` bytes shared with ``other`` bytes of something else (a
    logger's database, a photo library): free = capacity - other - the blobs under root. What a
    scenario swaps in as node.disk, to test the free-space floor without filling a real disk."""

    def __init__(self, root, capacity: int, other: int = 0):
        self._root, self.capacity, self.other = Path(root), capacity, other

    def free_bytes(self) -> int:
        from storeutil import used_bytes
        return max(0, self.capacity - self.other - used_bytes(self._root))


class SimCluster:
    def __init__(self, home: str | Path, cluster_id: str = "cluster-1"):
        self.home = Path(home)
        self.cluster_id = cluster_id
        self.nodes: dict[str, StoreNode] = {}
        self.offline: set[str] = set()
        self.partitions: list[set[str]] = []          # empty = fully connected

    # ── membership ───────────────────────────────────────────────────────────

    def _new_node(self, name: str, cluster_id: Optional[str], card, config) -> StoreNode:
        """Build one device and give it its peers client. Subclasses override this
        to change the transport (HttpCluster serves each device over real HTTP)."""
        node = StoreNode(name, self.home / name, cluster_id=cluster_id,
                         card=card, config=config)
        node.peers = SimPeers(self, name)
        return node

    def add_node(self, name: str, card: Optional[dict] = None,
                 config: Optional[dict] = None, cluster_id: Optional[str] = None) -> StoreNode:
        """Add a device already joined to this cluster — or, with ``cluster_id``, one
        that belongs to a DIFFERENT cluster (a stranger on the network)."""
        node = self._new_node(name, cluster_id or self.cluster_id, card, config)
        self.nodes[name] = node
        return node

    def found(self, name: str, card: Optional[dict] = None,
              config: Optional[dict] = None) -> StoreNode:
        """Add the first device and have it found the cluster (the one node that
        starts with no cluster_id); everyone else is added already joined."""
        node = self._new_node(name, None, card, config)
        self.nodes[name] = node
        node.run("create_cluster", cluster_id=self.cluster_id)
        node.adopt_cluster(self.cluster_id)
        return node

    def close(self) -> None:
        for node in self.nodes.values():
            node.close()

    # ── the network ──────────────────────────────────────────────────────────

    def reachable(self, src: str, dst: str) -> bool:
        if dst not in self.nodes or dst in self.offline or src in self.offline:
            return False
        if not self.partitions:
            return True
        return any(src in group and dst in group for group in self.partitions)

    def surface(self, src: str, dst: str) -> PeerSurface:
        if not self.reachable(src, dst):
            raise PeerUnreachable(f"{dst} is unreachable from {src}")
        return self.nodes[dst].surface

    def settle(self, max_rounds: int = 100) -> None:
        """Let every ONLINE device run until the whole cluster is idle: each
        round, each device (in name order, deterministic) drains its queue and
        its peers' pull requests. An offline device does nothing — its work
        waits for it, as a sleeping laptop's would."""
        for _ in range(max_rounds):
            busy = False
            for name in sorted(self.nodes):
                node = self.nodes[name]
                if name not in self.offline and node.has_work():
                    node.drain()
                    busy = True
            if not busy:
                return
        raise RuntimeError(f"cluster did not settle in {max_rounds} rounds")

    def set_offline(self, name: str, offline: bool = True) -> None:
        (self.offline.add if offline else self.offline.discard)(name)

    def partition(self, groups: list[list[str]]) -> None:
        self.partitions = [set(g) for g in groups]

    def heal(self) -> None:
        self.partitions = []
