# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.commands import SyncPeer
from gen_def.pydantic.environment import Store


@dataclass
class sync_on_node_announced_emitters:
    sync_peer: Callable[[SyncPeer], None]


@dataclass
class sync_on_node_announced_env:
    store: Store


@dataclass
class sync_on_node_announced_context:
    emit: sync_on_node_announced_emitters
    env: sync_on_node_announced_env
