# A blob's registered catalog row, with the chunk recipe when chunked.
from gen_int.python.query.get_blob import get_blob_query, get_blob_context
from gen_def.pydantic.query.get_blob import GetBlobInput, GetBlobOutput
from gen_def.sqla.models.pool import Blob
from storeutil import iso, parse_json_list


def get_blob(input: GetBlobInput, context: get_blob_context) -> GetBlobOutput:
    row = context.adapter.session.get(Blob, input.blob_hash)
    if row is None:
        return GetBlobOutput(found=False)
    return GetBlobOutput(
        found=True, blob_hash=row.blob_hash, byte_size=row.byte_size,
        collection=row.collection, first_seen_at=iso(row.first_seen_at),
        chunk_size=row.chunk_size, chunk_hashes=parse_json_list(row.chunk_hashes_json))
