# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.commands import EvictBlob
from gen_def.pydantic.query.get_eviction_candidates import GetEvictionCandidatesInput, GetEvictionCandidatesOutput
from gen_def.pydantic.environment import Store


@dataclass
class evict_on_space_pressure_emitters:
    evict_blob: Callable[[EvictBlob], None]


@dataclass
class evict_on_space_pressure_queries:
    get_eviction_candidates: Callable[[GetEvictionCandidatesInput], GetEvictionCandidatesOutput]


@dataclass
class evict_on_space_pressure_env:
    store: Store


@dataclass
class evict_on_space_pressure_context:
    emit: evict_on_space_pressure_emitters
    query: evict_on_space_pressure_queries
    env: evict_on_space_pressure_env
