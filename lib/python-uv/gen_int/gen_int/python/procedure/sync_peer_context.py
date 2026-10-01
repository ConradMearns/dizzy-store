# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import PeerLinkChanged
from gen_def.pydantic.query.get_peer_link import GetPeerLinkInput, GetPeerLinkOutput
from gen_def.pydantic.environment import Store
from gen_def.pydantic.environment import Peers
from gen_def.pydantic.telemetry import PeerHealth
from gen_def.pydantic.telemetry import Progress


@dataclass
class sync_peer_emitters:
    peer_link_changed: Callable[[PeerLinkChanged], None]


@dataclass
class sync_peer_queries:
    get_peer_link: Callable[[GetPeerLinkInput], GetPeerLinkOutput]


@dataclass
class sync_peer_env:
    store: Store
    peers: Peers


@dataclass
class sync_peer_telemetry:
    peer_health: Callable[[PeerHealth], None]
    progress: Callable[[Progress], None]


@dataclass
class sync_peer_context:
    emit: sync_peer_emitters
    query: sync_peer_queries
    env: sync_peer_env
    telemetry: sync_peer_telemetry
