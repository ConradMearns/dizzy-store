# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import PeerLinkChanged
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class peer_link_upsert_context:
    adapter: SqlaAdapter


class peer_link_upsert_projection(Protocol):
    """Upsert the (node_id, peer_id) peer_links row with healthy and changed_at."""

    def __call__(self, event: PeerLinkChanged, context: peer_link_upsert_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
