# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import BlobEvicted
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class blob_location_evicted_context:
    adapter: SqlaAdapter


class blob_location_evicted_projection(Protocol):
    """Set the (blob_hash, node_id, epoch) location to 'evicted'."""

    def __call__(self, event: BlobEvicted, context: blob_location_evicted_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
