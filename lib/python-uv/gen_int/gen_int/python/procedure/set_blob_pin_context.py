# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import BlobPinSet
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput, GetBlobReplicasOutput
from gen_def.pydantic.environment import Store


@dataclass
class set_blob_pin_emitters:
    blob_pin_set: Callable[[BlobPinSet], None]


@dataclass
class set_blob_pin_queries:
    get_blob_replicas: Callable[[GetBlobReplicasInput], GetBlobReplicasOutput]


@dataclass
class set_blob_pin_env:
    store: Store


@dataclass
class set_blob_pin_context:
    emit: set_blob_pin_emitters
    query: set_blob_pin_queries
    env: set_blob_pin_env
