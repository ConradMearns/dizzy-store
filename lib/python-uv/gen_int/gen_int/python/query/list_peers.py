# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.list_peers import ListPeersInput, ListPeersOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class list_peers_context:
    adapter: SqlaAdapter


class list_peers_query(Protocol):
    """Every known node except a given node_id, with its card — the peer set for the host's sync sweep."""

    def __call__(
        self, input: ListPeersInput, context: list_peers_context
    ) -> ListPeersOutput:
        ...
