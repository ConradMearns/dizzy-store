# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import BlobRegistered
from gen_def.pydantic.events import BlobStored
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput, GetBlobReplicasOutput
from gen_def.pydantic.query.get_blob import GetBlobInput, GetBlobOutput
from gen_def.pydantic.environment import Store
from gen_def.pydantic.telemetry import Progress


@dataclass
class adopt_collection_emitters:
    blob_registered: Callable[[BlobRegistered], None]
    blob_stored: Callable[[BlobStored], None]


@dataclass
class adopt_collection_queries:
    get_blob_replicas: Callable[[GetBlobReplicasInput], GetBlobReplicasOutput]
    get_blob: Callable[[GetBlobInput], GetBlobOutput]


@dataclass
class adopt_collection_env:
    store: Store


@dataclass
class adopt_collection_telemetry:
    progress: Callable[[Progress], None]


@dataclass
class adopt_collection_context:
    emit: adopt_collection_emitters
    query: adopt_collection_queries
    env: adopt_collection_env
    telemetry: adopt_collection_telemetry
