# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import BlobAccessRecorded
from gen_def.pydantic.environment import Store


@dataclass
class record_blob_access_emitters:
    blob_access_recorded: Callable[[BlobAccessRecorded], None]


@dataclass
class record_blob_access_env:
    store: Store


@dataclass
class record_blob_access_context:
    emit: record_blob_access_emitters
    env: record_blob_access_env
