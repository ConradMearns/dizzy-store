# One link's state; an unknown link counts as healthy so the first failure is a flip.
from gen_int.python.query.get_peer_link import get_peer_link_query, get_peer_link_context
from gen_def.pydantic.query.get_peer_link import GetPeerLinkInput, GetPeerLinkOutput
from gen_def.sqla.models.pool import PeerLink
from storeutil import iso


def get_peer_link(input: GetPeerLinkInput, context: get_peer_link_context) -> GetPeerLinkOutput:
    row = context.adapter.session.get(PeerLink, f"{input.node_id}|{input.peer_id}")
    if row is None:
        return GetPeerLinkOutput(known=False, healthy=True)
    return GetPeerLinkOutput(known=True, healthy=bool(row.healthy),
                             changed_at=iso(row.changed_at))
