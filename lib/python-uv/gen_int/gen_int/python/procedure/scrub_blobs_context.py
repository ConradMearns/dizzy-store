# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Callable

from gen_def.pydantic.events import BlobCorrupt
from gen_def.pydantic.events import ScrubCompleted
from gen_def.pydantic.query.get_blobs_held import GetBlobsHeldInput, GetBlobsHeldOutput
from gen_def.pydantic.environment import Store
from gen_def.pydantic.telemetry import Progress


@dataclass
class scrub_blobs_emitters:
    blob_corrupt: Callable[[BlobCorrupt], None]
    scrub_completed: Callable[[ScrubCompleted], None]


@dataclass
class scrub_blobs_queries:
    get_blobs_held: Callable[[GetBlobsHeldInput], GetBlobsHeldOutput]


@dataclass
class scrub_blobs_env:
    store: Store


@dataclass
class scrub_blobs_telemetry:
    progress: Callable[[Progress], None]


@dataclass
class scrub_blobs_context:
    emit: scrub_blobs_emitters
    query: scrub_blobs_queries
    env: scrub_blobs_env
    telemetry: scrub_blobs_telemetry
