# A PEER announced itself -> dispatch sync_peer 'both': joining the pool is being
# announced, then syncing. Idempotent — a re-announcement costs one heads exchange.
from gen_int.python.policy.sync_on_node_announced_protocol import sync_on_node_announced_protocol
from gen_int.python.policy.sync_on_node_announced_context import sync_on_node_announced_context
from gen_def.pydantic.events import NodeAnnounced
from gen_def.pydantic.commands import SyncPeer
from storeutil import is_fresh, now_utc


def sync_on_node_announced(
    event: NodeAnnounced,
    context: sync_on_node_announced_context,
) -> None:
    store = context.env.store
    if event.node_id == store.node_id:
        return
    if not is_fresh(event.occurred_at, store.live_window_s):
        return                                   # a replayed announcement is not a join
    context.emit.sync_peer(SyncPeer(
        peer_id=event.node_id, direction="both", occurred_at=now_utc()))
