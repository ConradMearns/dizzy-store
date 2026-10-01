# Upsert the (node, peer) peer_links row — latest occurred_at wins (ties: digest).
from gen_int.python.projection.peer_link_upsert_projection import peer_link_upsert_projection
from gen_int.python.projection.peer_link_upsert_projection import peer_link_upsert_context
from gen_def.pydantic.events import PeerLinkChanged
from gen_def.sqla.models.pool import PeerLink
from storeutil import lww_wins, naive_utc, payload_digest


def peer_link_upsert(
    event: PeerLinkChanged,
    context: peer_link_upsert_context,
) -> None:
    session = context.adapter.session
    key = f"{event.node_id}|{event.peer_id}"
    digest = payload_digest(event)
    row = session.get(PeerLink, key)
    if row is not None and not lww_wins(event.occurred_at, digest, row.changed_at, row.digest):
        return
    if row is None:
        row = PeerLink(id=key, node_id=event.node_id, peer_id=event.peer_id)
        session.add(row)
    row.healthy = bool(event.healthy)
    row.changed_at = naive_utc(event.occurred_at)
    row.digest = digest
    session.flush()
