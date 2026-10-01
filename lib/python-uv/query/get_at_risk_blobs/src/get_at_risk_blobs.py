# Registered blobs held by fewer distinct sites than their collection requires;
# sites_holding = 0 is LOSS. The first cut of the safety measure.
from gen_int.python.query.get_at_risk_blobs import get_at_risk_blobs_query, get_at_risk_blobs_context
from gen_def.pydantic.query.get_at_risk_blobs import GetAtRiskBlobsInput, GetAtRiskBlobsOutput
from gen_def.sqla.models.pool import Blob
from storeutil import PlacementIndex, iso, now_utc


def get_at_risk_blobs(input: GetAtRiskBlobsInput, context: get_at_risk_blobs_context) -> GetAtRiskBlobsOutput:
    session = context.adapter.session
    q = session.query(Blob)
    if input.collection:
        q = q.filter(Blob.collection == input.collection)
    index = PlacementIndex(session)          # one query for every blob's holders
    now = now_utc()
    rows = []
    for blob in q:
        policy = index.policy(blob.collection)
        sites = {n.site for _l, n in index.counted_copies(blob.blob_hash, blob.collection, now)}
        if len(sites) < policy.min_sites:
            rows.append((len(sites), blob, policy.min_sites))
    rows.sort(key=lambda r: (r[0], r[1].first_seen_at, r[1].blob_hash))
    if input.limit:
        rows = rows[: input.limit]
    return GetAtRiskBlobsOutput(
        blob_hashes=[b.blob_hash for _h, b, _m in rows],
        byte_sizes=[b.byte_size for _h, b, _m in rows],
        collections=[b.collection for _h, b, _m in rows],
        first_seen_ats=[iso(b.first_seen_at) for _h, b, _m in rows],
        sites_holding=[h for h, _b, _m in rows], sites_needed=[m for _h, _b, m in rows])
