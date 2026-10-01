# Exchange logs with one peer. The anti-entropy itself (heads, ancestry, hash
# verification, fold, react-on-replicate) is the event store's, reached through
# env.peers — merged events are NOT emitted here. This procedure owns only the
# cluster check and the link's health transitions.
from gen_int.python.procedure.sync_peer_protocol import sync_peer_protocol
from gen_int.python.procedure.sync_peer_context import sync_peer_context
from gen_def.pydantic.commands import SyncPeer
from gen_def.pydantic.events import PeerLinkChanged
from gen_def.pydantic.query.get_peer_link import GetPeerLinkInput
from gen_def.pydantic.telemetry import PeerHealth, Progress
from storeutil import PeerUnreachable, now_utc, strictly_after


def sync_peer(
    context: sync_peer_context,
    command: SyncPeer,
) -> None:
    store, peers = context.env.store, context.env.peers
    if command.direction not in ("pull", "push", "both"):
        raise ValueError("direction must be 'pull', 'push' or 'both'")
    link = context.query.get_peer_link(
        GetPeerLinkInput(node_id=store.node_id, peer_id=command.peer_id))

    def flip(healthy: bool, reason: str | None = None) -> None:
        if bool(link.healthy) == healthy:
            return                                # not a transition: say nothing
        context.emit.peer_link_changed(PeerLinkChanged(
            node_id=store.node_id, peer_id=command.peer_id, healthy=healthy,
            reason=reason, occurred_at=strictly_after(now_utc(), link.changed_at)))

    pulled = 0
    try:
        theirs = peers.cluster_id(command.peer_id)
        if store.cluster_id and theirs and theirs != store.cluster_id:
            raise ValueError(f"peer {command.peer_id} belongs to cluster {theirs!r}, "
                             f"not {store.cluster_id!r}")
        if command.direction in ("pull", "both"):
            pulled = peers.pull_from(command.peer_id)
        if command.direction in ("push", "both"):
            peers.request_pull(command.peer_id)   # "push": ask the peer to pull from me
    except PeerUnreachable as exc:
        context.telemetry.peer_health(PeerHealth(
            peer_id=command.peer_id, reachable=False, detail=str(exc)))
        flip(False, str(exc))
        return
    context.telemetry.peer_health(PeerHealth(peer_id=command.peer_id, reachable=True))
    flip(True)
    context.telemetry.progress(Progress(
        stage="sync", detail=f"{command.peer_id} {command.direction}: pulled {pulled}"))
