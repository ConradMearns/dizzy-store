# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import CollectionPolicySet
from gen_def.pydantic.query.get_collection_policy import GetCollectionPolicyInput, GetCollectionPolicyOutput


@dataclass
class set_collection_policy_emitters:
    collection_policy_set: Callable[[CollectionPolicySet], None]


@dataclass
class set_collection_policy_queries:
    get_collection_policy: Callable[[GetCollectionPolicyInput], GetCollectionPolicyOutput]


@dataclass
class set_collection_policy_context:
    emit: set_collection_policy_emitters
    query: set_collection_policy_queries
