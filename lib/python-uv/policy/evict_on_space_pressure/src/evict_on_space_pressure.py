# THIS node is over its high watermark -> dispatch evict_blob for the candidates
# that cover bytes_to_free, bounded per event; the next pressure reading follows
# if more is needed. evict_blob re-verifies each, so a stale candidate is refused.
from gen_int.python.policy.evict_on_space_pressure_protocol import evict_on_space_pressure_protocol
from gen_int.python.policy.evict_on_space_pressure_context import evict_on_space_pressure_context
from gen_def.pydantic.events import SpacePressureDetected
from gen_def.pydantic.commands import EvictBlob
from gen_def.pydantic.query.get_eviction_candidates import GetEvictionCandidatesInput
from storeutil import now_utc


def evict_on_space_pressure(
    event: SpacePressureDetected,
    context: evict_on_space_pressure_context,
) -> None:
    store = context.env.store
    if event.node_id != store.node_id:
        return                                   # a peer's pressure is not mine to relieve
    candidates = context.query.get_eviction_candidates(GetEvictionCandidatesInput(
        node_id=store.node_id, bytes_needed=event.bytes_to_free,
        limit=store.max_dispatch_per_event))
    for blob_hash in candidates.blob_hashes[: store.max_dispatch_per_event]:
        context.emit.evict_blob(EvictBlob(
            blob_hash=blob_hash, reason="pressure", occurred_at=now_utc()))
