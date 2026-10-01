# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import AdoptCollection
from gen_int.python.procedure.adopt_collection_context import (
    adopt_collection_context,
)


class adopt_collection_protocol(Protocol):
    """EFFECT: walk root. A 'cas' file whose name is already held here (get_blob_replicas) is skipped without reading it — scrub covers it — so re-running an adoption costs a directory walk. Every other file is HASHED (rate-limited by env.store.scrub_bytes_per_sec); a 'cas' file whose bytes do not match its name is skipped, reporting to progress. Then copy it into env.store.root's sharded layout — or, with link: true, hard-link it (a file already at the address is kept only if it IS those bytes, else replaced atomically; nothing at the original path is ever touched) — emit blob_registered when new to the cluster (get_blob) and blob_stored (source 'adopted'). Forwards a progress summary."""

    def __call__(
        self,
        context: adopt_collection_context,
        command: AdoptCollection,
    ) -> None:
        ...
