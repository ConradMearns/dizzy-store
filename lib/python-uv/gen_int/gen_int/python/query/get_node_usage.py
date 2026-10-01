# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_node_usage import GetNodeUsageInput, GetNodeUsageOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_node_usage_context:
    adapter: SqlaAdapter


class get_node_usage_query(Protocol):
    """What a node holds (input: node_id): held_count and held_bytes of its 'present' locations under its current epoch — a cheap aggregate, unlike get_drain_remaining. Readers: replicate_blob's budget check, the daemon's status."""

    def __call__(
        self, input: GetNodeUsageInput, context: get_node_usage_context
    ) -> GetNodeUsageOutput:
        ...
