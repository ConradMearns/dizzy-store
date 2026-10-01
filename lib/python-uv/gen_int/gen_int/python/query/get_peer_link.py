# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_peer_link import GetPeerLinkInput, GetPeerLinkOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_peer_link_context:
    adapter: SqlaAdapter


class get_peer_link_query(Protocol):
    """One link's state (input: node_id, peer_id): healthy, changed_at; healthy=true for a link never seen."""

    def __call__(
        self, input: GetPeerLinkInput, context: get_peer_link_context
    ) -> GetPeerLinkOutput:
        ...
