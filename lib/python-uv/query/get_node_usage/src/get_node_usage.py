# What a node holds: a cheap aggregate over its 'present' locations (current epoch).
from sqlalchemy import func
from gen_int.python.query.get_node_usage import get_node_usage_query, get_node_usage_context
from gen_def.pydantic.query.get_node_usage import GetNodeUsageInput, GetNodeUsageOutput
from gen_def.sqla.models.pool import Blob, BlobLocation, Node


def get_node_usage(input: GetNodeUsageInput, context: get_node_usage_context) -> GetNodeUsageOutput:
    session = context.adapter.session
    me = session.get(Node, input.node_id)
    if me is None:
        return GetNodeUsageOutput(held_count=0, held_bytes=0)
    count, size = (session.query(func.count(BlobLocation.id),
                                 func.coalesce(func.sum(Blob.byte_size), 0))
                   .join(Blob, Blob.blob_hash == BlobLocation.blob_hash)
                   .filter(BlobLocation.node_id == me.node_id, BlobLocation.epoch == me.epoch,
                           BlobLocation.state == "present").one())
    return GetNodeUsageOutput(held_count=int(count), held_bytes=int(size))
