# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import BlobPinSet
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class blob_location_pin_context:
    adapter: SqlaAdapter


class blob_location_pin_projection(Protocol):
    """Set pinned on the (blob_hash, node_id, epoch) location from blob_pin_set."""

    def __call__(self, event: BlobPinSet, context: blob_location_pin_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
