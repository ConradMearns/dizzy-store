# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import ScrubCompleted
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class scrub_state_store_context:
    adapter: SqlaAdapter


class scrub_state_store_projection(Protocol):
    """Upsert scrub_state (node_id, collection, epoch): while a pass is in progress keep its cursor and pass_started_at; on pass_complete clear them and set last_full_pass_at to the pass's START (pass_started_at) — conservative: blobs verified early in a long pass are only as fresh as its beginning."""

    def __call__(self, event: ScrubCompleted, context: scrub_state_store_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
