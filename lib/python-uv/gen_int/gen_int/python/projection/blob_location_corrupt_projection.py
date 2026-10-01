# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import BlobCorrupt
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class blob_location_corrupt_context:
    adapter: SqlaAdapter


class blob_location_corrupt_projection(Protocol):
    """Set the (blob_hash, node_id, epoch) location to 'corrupt', so no peer picks it as a source and it stops counting toward min_sites."""

    def __call__(self, event: BlobCorrupt, context: blob_location_corrupt_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
