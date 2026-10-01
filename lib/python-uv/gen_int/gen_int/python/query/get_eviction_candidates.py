# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_eviction_candidates import GetEvictionCandidatesInput, GetEvictionCandidatesOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_eviction_candidates_context:
    adapter: SqlaAdapter


class get_eviction_candidates_query(Protocol):
    """Blobs a node may drop (input: node_id, bytes_needed, limit): its 'present', unpinned locations in evictable collections that OTHER non- draining nodes hold fresh and 'present' across at least min_sites distinct sites, including a non-draining archive. A 'hot' node gets them least recently TOUCHED first (last read, else when stored), skipping collections it WANTS in full, stopping once bytes_needed is covered; a draining node gets all of them; a 'cold' node gets none. Advisory — evict_blob re-checks live. Readers: evict_on_space_pressure and the host's drain sweep."""

    def __call__(
        self, input: GetEvictionCandidatesInput, context: get_eviction_candidates_context
    ) -> GetEvictionCandidatesOutput:
        ...
