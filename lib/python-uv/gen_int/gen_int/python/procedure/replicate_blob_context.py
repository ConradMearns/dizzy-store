# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import BlobStored
from gen_def.pydantic.events import BlobReplicationFailed
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput, GetBlobReplicasOutput
from gen_def.pydantic.query.get_blob import GetBlobInput, GetBlobOutput
from gen_def.pydantic.query.get_node_usage import GetNodeUsageInput, GetNodeUsageOutput
from gen_def.pydantic.environment import Store
from gen_def.pydantic.environment import Peers
from gen_def.pydantic.environment import Disk
from gen_def.pydantic.telemetry import TransferProgress
from gen_def.pydantic.telemetry import PeerHealth


@dataclass
class replicate_blob_emitters:
    blob_stored: Callable[[BlobStored], None]
    blob_replication_failed: Callable[[BlobReplicationFailed], None]


@dataclass
class replicate_blob_queries:
    get_blob_replicas: Callable[[GetBlobReplicasInput], GetBlobReplicasOutput]
    get_blob: Callable[[GetBlobInput], GetBlobOutput]
    get_node_usage: Callable[[GetNodeUsageInput], GetNodeUsageOutput]


@dataclass
class replicate_blob_env:
    store: Store
    peers: Peers
    disk: Disk


@dataclass
class replicate_blob_telemetry:
    transfer_progress: Callable[[TransferProgress], None]
    peer_health: Callable[[PeerHealth], None]


@dataclass
class replicate_blob_context:
    emit: replicate_blob_emitters
    query: replicate_blob_queries
    env: replicate_blob_env
    telemetry: replicate_blob_telemetry
