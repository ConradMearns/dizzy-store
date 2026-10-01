# What a node still holds, and how much of it is not yet droppable.
from gen_int.python.query.get_drain_remaining import get_drain_remaining_query, get_drain_remaining_context
from gen_def.pydantic.query.get_drain_remaining import GetDrainRemainingInput, GetDrainRemainingOutput
from gen_def.sqla.models.pool import Blob, BlobLocation, Node
from storeutil import PlacementIndex, now_utc


def get_drain_remaining(input: GetDrainRemainingInput, context: get_drain_remaining_context) -> GetDrainRemainingOutput:
    session = context.adapter.session
    me = session.get(Node, input.node_id)
    if me is None:
        return GetDrainRemainingOutput(held_count=0, held_bytes=0, unsafe_count=0)
    held = (session.query(BlobLocation, Blob)
            .join(Blob, Blob.blob_hash == BlobLocation.blob_hash)
            .filter(BlobLocation.node_id == me.node_id, BlobLocation.epoch == me.epoch,
                    BlobLocation.state == "present").all())
    index = PlacementIndex(session)
    now = now_utc()
    unsafe = 0
    for loc, blob in held:
        ok, _s, _a = index.safe_to_drop(me.node_id, blob.blob_hash, blob.collection, now)
        if loc.pinned or not index.policy(blob.collection).evictable or not ok:
            unsafe += 1
    return GetDrainRemainingOutput(
        held_count=len(held), held_bytes=sum(b.byte_size for _l, b in held),
        unsafe_count=unsafe)
