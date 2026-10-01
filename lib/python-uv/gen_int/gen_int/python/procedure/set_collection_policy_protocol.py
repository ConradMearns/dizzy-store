# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import SetCollectionPolicy
from gen_int.python.procedure.set_collection_policy_context import (
    set_collection_policy_context,
)


class set_collection_policy_protocol(Protocol):
    """Reject min_sites < 1, then emit collection_policy_set — with occurred_at bumped to just after the collection's current declaration when the clock has not moved on (get_collection_policy)."""

    def __call__(
        self,
        context: set_collection_policy_context,
        command: SetCollectionPolicy,
    ) -> None:
        ...
