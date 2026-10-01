# Upsert the (blob, node, epoch) location as 'present', keeping pin + last_access_at.
# Tolerates arriving before the blob's blob_registered.
from gen_int.python.projection.blob_location_present_projection import blob_location_present_projection
from gen_int.python.projection.blob_location_present_projection import blob_location_present_context
from gen_def.pydantic.events import BlobStored
from gen_def.sqla.models.pool import BlobLocation
from storeutil import loc_id, naive_utc


def blob_location_present(
    event: BlobStored,
    context: blob_location_present_context,
) -> None:
    session = context.adapter.session
    key = loc_id(event.node_id, event.epoch, event.blob_hash)
    row = session.get(BlobLocation, key)
    if row is None:
        row = BlobLocation(id=key, blob_hash=event.blob_hash, node_id=event.node_id,
                           epoch=event.epoch, pinned=False)
        session.add(row)
    row.state = "present"
    row.stored_at = naive_utc(event.occurred_at)
    session.flush()
