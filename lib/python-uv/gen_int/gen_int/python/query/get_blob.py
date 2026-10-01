# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_blob import GetBlobInput, GetBlobOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_blob_context:
    adapter: SqlaAdapter


class get_blob_query(Protocol):
    """A blob's catalog row (input: blob_hash): byte_size, collection, first_seen_at, and chunk_size + ordered chunk_hashes when chunked; found flag (false means new to the cluster). Also the chunk recipe replicate_blob and the edge's streaming read follow."""

    def __call__(
        self, input: GetBlobInput, context: get_blob_context
    ) -> GetBlobOutput:
        ...
