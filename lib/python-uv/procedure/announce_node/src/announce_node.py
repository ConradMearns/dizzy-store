# Declare this node's public card; identity (node_id, cluster_id, epoch) comes from env.store.
from gen_int.python.procedure.announce_node_protocol import announce_node_protocol
from gen_int.python.procedure.announce_node_context import announce_node_context
from gen_def.pydantic.commands import AnnounceNode
from gen_def.pydantic.events import NodeAnnounced
from gen_def.pydantic.query.get_node_profile import GetNodeProfileInput
from storeutil import strictly_after

ROLES = ("hot", "archive", "cold")


def announce_node(
    context: announce_node_context,
    command: AnnounceNode,
) -> None:
    store = context.env.store
    if command.role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {command.role!r}")
    if not command.site.strip():
        raise ValueError("site is required — it is the failure domain min_sites counts")
    if not store.cluster_id:
        raise ValueError("this node has no cluster_id — found or join a cluster first")
    prior = context.query.get_node_profile(GetNodeProfileInput(node_id=store.node_id))
    occurred_at = strictly_after(command.occurred_at, prior.announced_at if prior.found else None)
    context.emit.node_announced(NodeAnnounced(
        node_id=store.node_id, cluster_id=store.cluster_id, epoch=store.epoch,
        role=command.role, site=command.site, location_note=command.location_note,
        endpoints=list(command.endpoints or []), wants=list(command.wants or []),
        draining=bool(command.draining), occurred_at=occurred_at))
