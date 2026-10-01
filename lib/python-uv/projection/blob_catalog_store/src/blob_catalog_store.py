# One row per registered blob. Two devices can register the same bytes concurrently
# (different collections, even), and each node folds the two events in whichever
# order they reach it — so the row keeps the EARLIEST registration by (occurred_at,
# payload digest), never "whichever folded first", and the earliest chunk recipe
# likewise. Equal event sets therefore give equal rows.
import json
from gen_int.python.projection.blob_catalog_store_projection import blob_catalog_store_projection
from gen_int.python.projection.blob_catalog_store_projection import blob_catalog_store_context
from gen_def.pydantic.events import BlobRegistered
from gen_def.sqla.models.pool import Blob
from storeutil import naive_utc, payload_digest


def blob_catalog_store(
    event: BlobRegistered,
    context: blob_catalog_store_context,
) -> None:
    session = context.adapter.session
    at, digest = naive_utc(event.occurred_at), payload_digest(event)
    key = (at, digest)
    has_recipe = bool(event.chunk_hashes)
    row = session.get(Blob, event.blob_hash)
    if row is None:
        session.add(Blob(
            blob_hash=event.blob_hash, byte_size=event.byte_size, collection=event.collection,
            first_seen_at=at, digest=digest,
            chunk_size=event.chunk_size if has_recipe else None,
            chunk_hashes_json=json.dumps(list(event.chunk_hashes)) if has_recipe else None,
            chunk_at=at if has_recipe else None, chunk_digest=digest if has_recipe else None))
    else:
        if key < (row.first_seen_at, row.digest):
            row.byte_size, row.collection = event.byte_size, event.collection
            row.first_seen_at, row.digest = at, digest
        if has_recipe and (row.chunk_hashes_json is None
                           or key < (row.chunk_at, row.chunk_digest)):
            row.chunk_size = event.chunk_size
            row.chunk_hashes_json = json.dumps(list(event.chunk_hashes))
            row.chunk_at, row.chunk_digest = at, digest
    session.flush()
