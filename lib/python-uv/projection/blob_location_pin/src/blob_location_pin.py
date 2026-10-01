# Set pinned on the (blob, node, epoch) location from blob_pin_set.
from gen_int.python.projection.blob_location_pin_projection import blob_location_pin_projection
from gen_int.python.projection.blob_location_pin_projection import blob_location_pin_context
from gen_def.pydantic.events import BlobPinSet
from gen_def.sqla.models.pool import BlobLocation
from storeutil import loc_id


def blob_location_pin(
    event: BlobPinSet,
    context: blob_location_pin_context,
) -> None:
    session = context.adapter.session
    row = session.get(BlobLocation, loc_id(event.node_id, event.epoch, event.blob_hash))
    if row is None:
        return          # a pin on a location that was never recorded: nothing to pin
    row.pinned = bool(event.pinned)
    session.flush()
