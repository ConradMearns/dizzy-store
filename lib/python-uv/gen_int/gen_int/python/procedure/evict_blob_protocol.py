# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import EvictBlob
from gen_int.python.procedure.evict_blob_context import (
    evict_blob_context,
)


class evict_blob_protocol(Protocol):
    """EFFECT: refuse (reported to progress; no event) unless ALL hold: the blob is unpinned here; its collection is evictable (get_collection_policy) and, for reason 'pressure', not one this node WANTS in full (get_node_profile) and not smaller than env.store.min_evict_bytes (get_blob byte_size; 0 = off — a drain takes small blobs too); this node's role permits the reason ('pressure' only for 'hot', 'drain' only while this node is draining, never 'cold'); and OTHER nodes' copies — per get_blob_replicas 'present', non-draining and fresh (verified_at within verify_max_age_days) — span at least min_sites distinct sites. Each candidate is then PROVEN live: asked (peers.verify_blob) to re-hash its file and report its own role and draining state; a peer that is unreachable, lacks the bytes, has the wrong bytes, or is itself draining does not count. Only when the proven copies span min_sites sites including a non-draining archive, delete the local file and emit blob_evicted with confirmed_sites."""

    def __call__(
        self,
        context: evict_blob_context,
        command: EvictBlob,
    ) -> None:
        ...
