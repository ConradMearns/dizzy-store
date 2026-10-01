# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput, GetBlobReplicasOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_blob_replicas_context:
    adapter: SqlaAdapter


class get_blob_replicas_query(Protocol):
    """Who holds a blob (input: blob_hash): every location — node_id, state, epoch, pinned, stored_at, last_access_at, verified_at (stored, or the last full scrub pass if later) — with its node's role, site and draining flag. Only locations under the node's CURRENT epoch are returned — a superseded life's claims stop counting. The single answer to "who has X?" and the idempotency check for put, adopt, replicate and pin."""

    def __call__(
        self, input: GetBlobReplicasInput, context: get_blob_replicas_context
    ) -> GetBlobReplicasOutput:
        ...
