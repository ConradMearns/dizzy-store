# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import NodeAnnounced
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class node_upsert_context:
    adapter: SqlaAdapter


class node_upsert_projection(Protocol):
    """Upsert a nodes row from node_announced: the latest occurred_at wins (ties: payload digest), so the row's epoch is the node's current life."""

    def __call__(self, event: NodeAnnounced, context: node_upsert_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
