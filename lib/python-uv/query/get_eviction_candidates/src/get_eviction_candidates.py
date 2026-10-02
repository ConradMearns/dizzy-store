# Blobs a node may drop (advisory — evict_blob re-checks, and PROVES live). Only a
# 'hot' node under pressure, or any non-cold draining node, ever has candidates.
# Under pressure a blob smaller than input.min_bytes (env.store.min_evict_bytes) is
# skipped BEFORE it can count toward bytes_needed or limit, so an exempt blob can
# neither inflate coverage nor starve the rest; a drain takes small blobs too.
from gen_int.python.query.get_eviction_candidates import get_eviction_candidates_query, get_eviction_candidates_context
from gen_def.pydantic.query.get_eviction_candidates import GetEvictionCandidatesInput, GetEvictionCandidatesOutput
from gen_def.sqla.models.pool import Blob, BlobLocation, Node
from storeutil import PlacementIndex, now_utc, parse_json_list


def get_eviction_candidates(input: GetEvictionCandidatesInput, context: get_eviction_candidates_context) -> GetEvictionCandidatesOutput:
    session = context.adapter.session
    me = session.get(Node, input.node_id)
    if me is None or me.role == "cold" or not (me.draining or me.role == "hot"):
        return GetEvictionCandidatesOutput(blob_hashes=[], byte_sizes=[], collections=[])
    wants = parse_json_list(me.wants_json)
    mine = (session.query(BlobLocation, Blob)
            .join(Blob, Blob.blob_hash == BlobLocation.blob_hash)
            .filter(BlobLocation.node_id == me.node_id, BlobLocation.epoch == me.epoch,
                    BlobLocation.state == "present", BlobLocation.pinned.is_(False)).all())
    # least recently TOUCHED first: the last read, else when it was stored. Rank
    # BEFORE checking safety, so a pressure tick evaluates only as many blobs as it
    # needs (the index makes each check a lookup, but a hot node may hold 15k blobs).
    mine.sort(key=lambda lb: (lb[0].last_access_at or lb[0].stored_at, lb[1].blob_hash))
    index = PlacementIndex(session)
    now = now_utc()
    out, covered = [], 0
    for loc, blob in mine:
        if (not me.draining and input.bytes_needed is not None
                and covered >= input.bytes_needed):
            break
        if input.limit and len(out) >= input.limit:
            break
        if not index.policy(blob.collection).evictable:
            continue
        if not me.draining and ("*" in wants or blob.collection in wants):
            continue                      # under pressure, never drop what this node WANTS in full
        if not me.draining and blob.byte_size < (input.min_bytes or 0):
            continue                      # ... nor a small blob (min_evict_bytes); a drain takes those too
        ok, _sites, _anchor = index.safe_to_drop(me.node_id, blob.blob_hash, blob.collection, now)
        if ok:
            out.append(blob)
            covered += blob.byte_size
    return GetEvictionCandidatesOutput(
        blob_hashes=[b.blob_hash for b in out], byte_sizes=[b.byte_size for b in out],
        collections=[b.collection for b in out])
