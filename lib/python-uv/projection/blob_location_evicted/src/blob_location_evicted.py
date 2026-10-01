# Set the (blob, node, epoch) location to 'evicted'; the row and its history stay.
from gen_int.python.projection.blob_location_evicted_projection import blob_location_evicted_projection
from gen_int.python.projection.blob_location_evicted_projection import blob_location_evicted_context
from gen_def.pydantic.events import BlobEvicted
from gen_def.sqla.models.pool import BlobLocation
from storeutil import loc_id


def blob_location_evicted(
    event: BlobEvicted,
    context: blob_location_evicted_context,
) -> None:
    session = context.adapter.session
    key = loc_id(event.node_id, event.epoch, event.blob_hash)
    row = session.get(BlobLocation, key)
    if row is None:
        row = BlobLocation(id=key, blob_hash=event.blob_hash, node_id=event.node_id,
                           epoch=event.epoch, pinned=False)
        session.add(row)
    row.state = "evicted"
    session.flush()
