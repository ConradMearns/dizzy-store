# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import ClusterCreated
from gen_def.pydantic.environment import Store


@dataclass
class create_cluster_emitters:
    cluster_created: Callable[[ClusterCreated], None]


@dataclass
class create_cluster_env:
    store: Store


@dataclass
class create_cluster_context:
    emit: create_cluster_emitters
    env: create_cluster_env
