# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import BlobRegistered
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class blob_catalog_store_context:
    adapter: SqlaAdapter


class blob_catalog_store_projection(Protocol):
    """Insert a blobs row from blob_registered when the hash is new; for a known hash keep the EARLIEST registration's byte_size, collection and first_seen_at by (occurred_at, payload digest) — so two devices that register one blob concurrently converge, whichever event a node folds first — and keep the earliest chunk recipe seen, likewise."""

    def __call__(self, event: BlobRegistered, context: blob_catalog_store_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
