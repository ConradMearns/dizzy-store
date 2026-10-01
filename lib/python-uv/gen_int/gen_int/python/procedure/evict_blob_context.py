# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import BlobEvicted
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput, GetBlobReplicasOutput
from gen_def.pydantic.query.get_blob import GetBlobInput, GetBlobOutput
from gen_def.pydantic.query.get_collection_policy import GetCollectionPolicyInput, GetCollectionPolicyOutput
from gen_def.pydantic.query.get_node_profile import GetNodeProfileInput, GetNodeProfileOutput
from gen_def.pydantic.environment import Store
from gen_def.pydantic.environment import Peers
from gen_def.pydantic.telemetry import PeerHealth
from gen_def.pydantic.telemetry import Progress


@dataclass
class evict_blob_emitters:
    blob_evicted: Callable[[BlobEvicted], None]


@dataclass
class evict_blob_queries:
    get_blob_replicas: Callable[[GetBlobReplicasInput], GetBlobReplicasOutput]
    get_blob: Callable[[GetBlobInput], GetBlobOutput]
    get_collection_policy: Callable[[GetCollectionPolicyInput], GetCollectionPolicyOutput]
    get_node_profile: Callable[[GetNodeProfileInput], GetNodeProfileOutput]


@dataclass
class evict_blob_env:
    store: Store
    peers: Peers


@dataclass
class evict_blob_telemetry:
    peer_health: Callable[[PeerHealth], None]
    progress: Callable[[Progress], None]


@dataclass
class evict_blob_context:
    emit: evict_blob_emitters
    query: evict_blob_queries
    env: evict_blob_env
    telemetry: evict_blob_telemetry
