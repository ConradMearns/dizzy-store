# Every known node except the given one, with its card.
from gen_int.python.query.list_peers import list_peers_query, list_peers_context
from gen_def.pydantic.query.list_peers import ListPeersInput, ListPeersOutput
from gen_def.sqla.models.pool import Node


def list_peers(input: ListPeersInput, context: list_peers_context) -> ListPeersOutput:
    rows = (context.adapter.session.query(Node)
            .filter(Node.node_id != input.node_id).order_by(Node.node_id).all())
    return ListPeersOutput(
        node_ids=[r.node_id for r in rows], cluster_ids=[r.cluster_id for r in rows],
        epochs=[r.epoch for r in rows], roles=[r.role for r in rows],
        sites=[r.site for r in rows], location_notes=[r.location_note or "" for r in rows],
        endpoints_jsons=[r.endpoints_json or "[]" for r in rows],
        wants_jsons=[r.wants_json or "[]" for r in rows],
        drainings=[bool(r.draining) for r in rows])
