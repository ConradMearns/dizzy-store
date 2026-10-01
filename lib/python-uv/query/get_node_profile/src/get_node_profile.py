# One node's public card by node_id.
from gen_int.python.query.get_node_profile import get_node_profile_query, get_node_profile_context
from gen_def.pydantic.query.get_node_profile import GetNodeProfileInput, GetNodeProfileOutput
from gen_def.sqla.models.pool import Node
from storeutil import iso, parse_json_list


def get_node_profile(input: GetNodeProfileInput, context: get_node_profile_context) -> GetNodeProfileOutput:
    row = context.adapter.session.get(Node, input.node_id)
    if row is None:
        return GetNodeProfileOutput(found=False)
    return GetNodeProfileOutput(
        found=True, node_id=row.node_id, cluster_id=row.cluster_id, epoch=row.epoch,
        role=row.role, site=row.site, location_note=row.location_note,
        endpoints=parse_json_list(row.endpoints_json),
        wants=parse_json_list(row.wants_json), draining=bool(row.draining),
        announced_at=iso(row.announced_at))
