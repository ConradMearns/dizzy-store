# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import BlobStored
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class blob_location_present_context:
    adapter: SqlaAdapter


class blob_location_present_projection(Protocol):
    """Upsert the (blob_hash, node_id, epoch) location as 'present' with stored_at, keeping any pin and last_access_at. Tolerates arriving before the blob's blob_registered."""

    def __call__(self, event: BlobStored, context: blob_location_present_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
