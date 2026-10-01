# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import ScrubBlobs
from gen_int.python.procedure.scrub_blobs_context import (
    scrub_blobs_context,
)


class scrub_blobs_protocol(Protocol):
    """EFFECT: iterate this node's held blobs from the saved cursor (get_blobs_held), re-hash each from disk within the max_bytes budget; for a mismatch or a missing / unreadable file (an I/O error is a bad copy, not a crash), quarantine what exists and emit blob_corrupt. Finish with scrub_completed carrying pass_started_at — when this pass began (now, for a fresh pass). Rate-limited by env.store.scrub_bytes_per_sec so it never starves serving. Forwards progress."""

    def __call__(
        self,
        context: scrub_blobs_context,
        command: ScrubBlobs,
    ) -> None:
        ...
