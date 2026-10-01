# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.commands import ReplicateBlob
from gen_def.pydantic.query.get_node_profile import GetNodeProfileInput, GetNodeProfileOutput
from gen_def.pydantic.query.get_blob import GetBlobInput, GetBlobOutput
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput, GetBlobReplicasOutput
from gen_def.pydantic.environment import Store


@dataclass
class replicate_on_peer_blob_stored_emitters:
    replicate_blob: Callable[[ReplicateBlob], None]


@dataclass
class replicate_on_peer_blob_stored_queries:
    get_node_profile: Callable[[GetNodeProfileInput], GetNodeProfileOutput]
    get_blob: Callable[[GetBlobInput], GetBlobOutput]
    get_blob_replicas: Callable[[GetBlobReplicasInput], GetBlobReplicasOutput]


@dataclass
class replicate_on_peer_blob_stored_env:
    store: Store


@dataclass
class replicate_on_peer_blob_stored_context:
    emit: replicate_on_peer_blob_stored_emitters
    query: replicate_on_peer_blob_stored_queries
    env: replicate_on_peer_blob_stored_env
