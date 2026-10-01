# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_blobs_held import GetBlobsHeldInput, GetBlobsHeldOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_blobs_held_context:
    adapter: SqlaAdapter


class get_blobs_held_query(Protocol):
    """A node's 'present' locations in hash order, continuing from its saved scrub cursor (input: node_id, optional collection, limit) — the stable iteration scrub resumes over — with the pass_started_at of the pass in progress."""

    def __call__(
        self, input: GetBlobsHeldInput, context: get_blobs_held_context
    ) -> GetBlobsHeldOutput:
        ...
