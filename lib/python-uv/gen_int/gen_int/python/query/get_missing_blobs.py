# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_missing_blobs import GetMissingBlobsInput, GetMissingBlobsOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_missing_blobs_context:
    adapter: SqlaAdapter


class get_missing_blobs_query(Protocol):
    """Registered blobs a node should hold but does not (input: node_id, limit, order 'newest' | 'smallest'): in a collection it wants ('*' = all), or pinned on it, with no 'present' location on it — so corrupt and evicted copies, and a wiped device's old claims, count as missing. Reader: the host's paced sweep."""

    def __call__(
        self, input: GetMissingBlobsInput, context: get_missing_blobs_context
    ) -> GetMissingBlobsOutput:
        ...
