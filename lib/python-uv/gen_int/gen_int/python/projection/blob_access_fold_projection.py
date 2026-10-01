# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import BlobAccessRecorded
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class blob_access_fold_context:
    adapter: SqlaAdapter


class blob_access_fold_projection(Protocol):
    """For each access entry, advance the location's last_access_at (max wins — idempotent under re-fold); entries for unknown locations are ignored."""

    def __call__(self, event: BlobAccessRecorded, context: blob_access_fold_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
