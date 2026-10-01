# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import ReplicateBlob
from gen_int.python.procedure.replicate_blob_context import (
    replicate_blob_context,
)


class replicate_blob_protocol(Protocol):
    """EFFECT: refuse when the blob would put this node over env.store.limit_bytes (get_node_usage) or leave the filesystem under env.store.min_free_bytes (env.disk.free_bytes()) — blob_replication_failed 'out_of_space'. Otherwise pick a source (from_node, else the best reachable holder per get_blob_replicas — never a corrupt or evicted copy). A plain blob streams into env.store.tmp_dir while hashing; a chunked one (get_blob has chunk_hashes) is fetched as chunks, one after another, each from the next holder in turn (parallel fetching is a later refinement), availability asked LIVE, each chunk verified into a staging directory that survives a crash (a restart re- hashes what is there and resumes). Verify the final sha256, move into place atomically, and emit blob_stored ONCE when whole (source = the reason). Idempotent: nothing when already held. On not-held / hash mismatch / no space emit blob_replication_failed and stop — retry is the sweep. Obeys env.store.max_bytes_per_sec (a token bucket). Forwards transfer progress and peer reachability. A recipe that fails the put_blob validation is ignored (the whole file is fetched and verified instead). A full disk is blob_replication_failed 'out_of_space', not a crash."""

    def __call__(
        self,
        context: replicate_blob_context,
        command: ReplicateBlob,
    ) -> None:
        ...
