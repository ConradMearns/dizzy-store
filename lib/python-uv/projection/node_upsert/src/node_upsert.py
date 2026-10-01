# Upsert a nodes row from node_announced — latest occurred_at wins (ties: payload digest).
import json
from gen_int.python.projection.node_upsert_projection import node_upsert_projection
from gen_int.python.projection.node_upsert_projection import node_upsert_context
from gen_def.pydantic.events import NodeAnnounced
from gen_def.sqla.models.pool import Node
from storeutil import lww_wins, naive_utc, payload_digest


def node_upsert(event: NodeAnnounced, context: node_upsert_context) -> None:
    session = context.adapter.session
    digest = payload_digest(event)
    row = session.get(Node, event.node_id)
    if row is not None and not lww_wins(event.occurred_at, digest, row.announced_at, row.digest):
        return
    if row is None:
        row = Node(node_id=event.node_id)
        session.add(row)
    row.cluster_id = event.cluster_id
    row.epoch = event.epoch
    row.role = event.role
    row.site = event.site
    row.location_note = event.location_note
    row.endpoints_json = json.dumps(list(event.endpoints or []))
    row.wants_json = json.dumps(list(event.wants or []))
    row.draining = bool(event.draining)
    row.announced_at = naive_utc(event.occurred_at)
    row.digest = digest
    session.flush()
