# Registered blobs a node should hold but does not: in a collection it wants
# (or pinned on it) with no 'present' location under its current epoch.
from sqlalchemy import or_
from gen_int.python.query.get_missing_blobs import get_missing_blobs_query, get_missing_blobs_context
from gen_def.pydantic.query.get_missing_blobs import GetMissingBlobsInput, GetMissingBlobsOutput
from gen_def.sqla.models.pool import Blob, BlobLocation, Node
from storeutil import parse_json_list


def get_missing_blobs(input: GetMissingBlobsInput, context: get_missing_blobs_context) -> GetMissingBlobsOutput:
    session = context.adapter.session
    me = session.get(Node, input.node_id)
    if me is None or me.draining:           # a draining node is never a replication target
        return GetMissingBlobsOutput(blob_hashes=[], byte_sizes=[], collections=[])
    wants = parse_json_list(me.wants_json)
    mine = session.query(BlobLocation).filter(
        BlobLocation.node_id == me.node_id, BlobLocation.epoch == me.epoch)
    present = {l.blob_hash for l in mine.filter(BlobLocation.state == "present")}
    pinned = {l.blob_hash for l in mine.filter(BlobLocation.pinned.is_(True))}
    q = session.query(Blob)
    wanted = [] if "*" in wants else [Blob.collection.in_(wants)]
    if "*" not in wants:
        q = q.filter(or_(*wanted, Blob.blob_hash.in_(pinned or {""})))
    blobs = [b for b in q if b.blob_hash not in present]
    if input.order == "smallest":
        blobs.sort(key=lambda b: (b.byte_size, b.blob_hash))
    else:
        blobs.sort(key=lambda b: (b.first_seen_at, b.blob_hash), reverse=True)
    if input.limit:
        blobs = blobs[: input.limit]
    return GetMissingBlobsOutput(
        blob_hashes=[b.blob_hash for b in blobs], byte_sizes=[b.byte_size for b in blobs],
        collections=[b.collection for b in blobs])
