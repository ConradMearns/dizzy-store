# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import NodeAnnounced
from gen_def.pydantic.query.get_node_profile import GetNodeProfileInput, GetNodeProfileOutput
from gen_def.pydantic.environment import Store


@dataclass
class announce_node_emitters:
    node_announced: Callable[[NodeAnnounced], None]


@dataclass
class announce_node_queries:
    get_node_profile: Callable[[GetNodeProfileInput], GetNodeProfileOutput]


@dataclass
class announce_node_env:
    store: Store


@dataclass
class announce_node_context:
    emit: announce_node_emitters
    query: announce_node_queries
    env: announce_node_env
