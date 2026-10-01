# A node's 'present' locations in hash order, continuing from its saved scrub cursor,
# with the start time of the pass in progress.
from gen_int.python.query.get_blobs_held import get_blobs_held_query, get_blobs_held_context
from gen_def.pydantic.query.get_blobs_held import GetBlobsHeldInput, GetBlobsHeldOutput
from gen_def.sqla.models.pool import Blob, BlobLocation, Node, ScrubState
from storeutil import iso, scrub_id


def get_blobs_held(input: GetBlobsHeldInput, context: get_blobs_held_context) -> GetBlobsHeldOutput:
    session = context.adapter.session
    me = session.get(Node, input.node_id)
    if me is None:
        return GetBlobsHeldOutput(blob_hashes=[], byte_sizes=[], collections=[], pass_started_at="")
    state = session.get(ScrubState, scrub_id(me.node_id, me.epoch, input.collection))
    cursor = state.cursor if state is not None else None
    started = iso(state.pass_started_at) if (state is not None and cursor) else ""
    q = (session.query(BlobLocation, Blob)
         .join(Blob, Blob.blob_hash == BlobLocation.blob_hash)
         .filter(BlobLocation.node_id == me.node_id, BlobLocation.epoch == me.epoch,
                 BlobLocation.state == "present"))
    if input.collection:
        q = q.filter(Blob.collection == input.collection)
    if cursor:
        q = q.filter(BlobLocation.blob_hash > cursor)
    q = q.order_by(BlobLocation.blob_hash)
    if input.limit:
        q = q.limit(input.limit)
    rows = q.all()
    return GetBlobsHeldOutput(
        blob_hashes=[b.blob_hash for _l, b in rows],
        byte_sizes=[b.byte_size for _l, b in rows],
        collections=[b.collection for _l, b in rows], pass_started_at=started)
