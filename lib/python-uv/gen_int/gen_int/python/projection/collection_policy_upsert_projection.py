# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.events import CollectionPolicySet
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class collection_policy_upsert_context:
    adapter: SqlaAdapter


class collection_policy_upsert_projection(Protocol):
    """Upsert a collection_policies row from collection_policy_set (latest occurred_at wins, ties by payload digest; an older one is ignored)."""

    def __call__(self, event: CollectionPolicySet, context: collection_policy_upsert_context) -> None:
        """Apply the projection — mutate model state in response to the event."""
        ...
