# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_collection_policy import GetCollectionPolicyInput, GetCollectionPolicyOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_collection_policy_context:
    adapter: SqlaAdapter


class get_collection_policy_query(Protocol):
    """A collection's policy (input: collection): min_sites, verify_max_age_days, evictable, declared_at. Defaults when undeclared: min_sites 1, verify_max_age_days 30, evictable true."""

    def __call__(
        self, input: GetCollectionPolicyInput, context: get_collection_policy_context
    ) -> GetCollectionPolicyOutput:
        ...
