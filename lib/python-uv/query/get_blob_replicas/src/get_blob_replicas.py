# Who holds a blob: every location under its node's CURRENT epoch, with when each
# copy was last proven good (stored, or the last full scrub pass if later).
from gen_int.python.query.get_blob_replicas import get_blob_replicas_query, get_blob_replicas_context
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput, GetBlobReplicasOutput
from gen_def.sqla.models.pool import Blob
from storeutil import PlacementIndex, iso


def get_blob_replicas(input: GetBlobReplicasInput, context: get_blob_replicas_context) -> GetBlobReplicasOutput:
    session = context.adapter.session
    blob = session.get(Blob, input.blob_hash)
    collection = blob.collection if blob is not None else ""
    index = PlacementIndex(session, [input.blob_hash])
    rows = index.holders(input.blob_hash)
    return GetBlobReplicasOutput(
        node_ids=[l.node_id for l, _n in rows], epochs=[l.epoch for l, _n in rows],
        states=[l.state for l, _n in rows], pinneds=[bool(l.pinned) for l, _n in rows],
        stored_ats=[iso(l.stored_at) for l, _n in rows],
        last_access_ats=[iso(l.last_access_at) for l, _n in rows],
        roles=[n.role for _l, n in rows], sites=[n.site for _l, n in rows],
        drainings=[bool(n.draining) for _l, n in rows],
        verified_ats=[iso(index.verified_at(l, collection)) for l, _n in rows])
