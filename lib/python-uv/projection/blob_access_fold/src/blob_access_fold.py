# Advance last_access_at (max wins — idempotent under re-fold); unknown locations ignored.
from gen_int.python.projection.blob_access_fold_projection import blob_access_fold_projection
from gen_int.python.projection.blob_access_fold_projection import blob_access_fold_context
from gen_def.pydantic.events import BlobAccessRecorded
from gen_def.sqla.models.pool import BlobLocation
from storeutil import loc_id, naive_utc


def blob_access_fold(
    event: BlobAccessRecorded,
    context: blob_access_fold_context,
) -> None:
    session = context.adapter.session
    for blob_hash, at in zip(event.blob_hashes, event.last_access_ats):
        row = session.get(BlobLocation, loc_id(event.node_id, event.epoch, blob_hash))
        if row is None:
            continue
        at = naive_utc(at)
        if row.last_access_at is None or at > row.last_access_at:
            row.last_access_at = at
    session.flush()
