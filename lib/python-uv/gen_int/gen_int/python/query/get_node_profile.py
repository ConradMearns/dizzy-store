# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_node_profile import GetNodeProfileInput, GetNodeProfileOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_node_profile_context:
    adapter: SqlaAdapter


class get_node_profile_query(Protocol):
    """One node's card (input: node_id): role, site, epoch, location_note, endpoints, wants, draining, announced_at; found flag."""

    def __call__(
        self, input: GetNodeProfileInput, context: get_node_profile_context
    ) -> GetNodeProfileOutput:
        ...
