# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import SyncPeer
from gen_int.python.procedure.sync_peer_context import (
    sync_peer_context,
)


class sync_peer_protocol(Protocol):
    """EFFECT: exchange logs with one peer. Refuse a peer whose cluster_id differs. PULL: reconcile the two logs' id sets, pull the missing events in batches (hash-verified, parents first), fold them through the projections and hand them to policies — the event store's anti-entropy, so they are NOT emitted here. PUSH: ask the peer to pull from this node. Emit peer_link_changed only when the link flips (get_peer_link), stamped strictly after the link's previous change; report every attempt to peer_health. Placement is never decided here — the merged events trigger each node's policies."""

    def __call__(
        self,
        context: sync_peer_context,
        command: SyncPeer,
    ) -> None:
        ...
