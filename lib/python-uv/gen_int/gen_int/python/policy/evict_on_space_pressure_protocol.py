# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.events import SpacePressureDetected
from gen_int.python.policy.evict_on_space_pressure_context import (
    evict_on_space_pressure_context,
)


class evict_on_space_pressure_protocol(Protocol):
    """When THIS node reports space_pressure_detected (peers' are ignored), dispatch evict_blob (reason 'pressure') for the get_eviction_candidates (min_bytes = env.store.min_evict_bytes) that cover bytes_to_free, at most env.store.max_dispatch_per_event; the next pressure reading follows if more is needed."""

    def __call__(
        self,
        event: SpacePressureDetected,
        context: evict_on_space_pressure_context,
    ) -> None:
        ...
