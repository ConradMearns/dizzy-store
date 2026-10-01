# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import PutBlob
from gen_int.python.procedure.put_blob_context import (
    put_blob_context,
)


class put_blob_protocol(Protocol):
    """Idempotent: emit NOTHING when this node already holds the hash (get_blob_replicas). Refuse a chunk recipe that could never be used (chunk_size > 0, ceil(byte_size / chunk_size) hashes, each a sha256). Otherwise emit blob_registered when the hash is new to the cluster (get_blob) — carrying the chunking when given — and blob_stored (source 'upload'). Does not touch the bytes beyond a size check."""

    def __call__(
        self,
        context: put_blob_context,
        command: PutBlob,
    ) -> None:
        ...
