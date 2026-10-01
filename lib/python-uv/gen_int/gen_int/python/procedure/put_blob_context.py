# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import BlobRegistered
from gen_def.pydantic.events import BlobStored
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput, GetBlobReplicasOutput
from gen_def.pydantic.query.get_blob import GetBlobInput, GetBlobOutput
from gen_def.pydantic.environment import Store


@dataclass
class put_blob_emitters:
    blob_registered: Callable[[BlobRegistered], None]
    blob_stored: Callable[[BlobStored], None]


@dataclass
class put_blob_queries:
    get_blob_replicas: Callable[[GetBlobReplicasInput], GetBlobReplicasOutput]
    get_blob: Callable[[GetBlobInput], GetBlobOutput]


@dataclass
class put_blob_env:
    store: Store


@dataclass
class put_blob_context:
    emit: put_blob_emitters
    query: put_blob_queries
    env: put_blob_env
