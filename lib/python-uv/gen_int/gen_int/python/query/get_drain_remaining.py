# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_drain_remaining import GetDrainRemainingInput, GetDrainRemainingOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_drain_remaining_context:
    adapter: SqlaAdapter


class get_drain_remaining_query(Protocol):
    """What a node still holds (input: node_id): count and bytes of its 'present' locations, and how many of those are not yet droppable (not safe elsewhere, pinned, or non-evictable) — the ones blocking its drain. Zero means it can be unplugged. Reader: UI/CLI."""

    def __call__(
        self, input: GetDrainRemainingInput, context: get_drain_remaining_context
    ) -> GetDrainRemainingOutput:
        ...
