# AUTO-GENERATED — do not edit
from dataclasses import dataclass
from typing import Protocol

from gen_def.pydantic.query.get_at_risk_blobs import GetAtRiskBlobsInput, GetAtRiskBlobsOutput
from gen_int.python.adapters.sqla import SqlaAdapter


@dataclass
class get_at_risk_blobs_context:
    adapter: SqlaAdapter


class get_at_risk_blobs_query(Protocol):
    """Registered blobs held by fewer distinct sites than their collection's min_sites (input: limit, optional collection): blob_hash, byte_size, collection, first_seen_at, sites_holding, sites_needed. A copy counts when 'present', on a non-draining node, and fresh — stored, or its node's last_full_pass_at, within verify_max_age_days. sites_holding = 0 is LOSS. The first cut of the safety measure; surfaced in the UI."""

    def __call__(
        self, input: GetAtRiskBlobsInput, context: get_at_risk_blobs_context
    ) -> GetAtRiskBlobsOutput:
        ...
