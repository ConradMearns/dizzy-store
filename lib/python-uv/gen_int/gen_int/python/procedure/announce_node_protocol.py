# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import AnnounceNode
from gen_int.python.procedure.announce_node_context import (
    announce_node_context,
)


class announce_node_protocol(Protocol):
    """Validate role and site, and emit node_announced for env.store.node_id carrying env.store.epoch and cluster_id. occurred_at is bumped to just after this node's previous announcement when the clock has not moved on (get_node_profile)."""

    def __call__(
        self,
        context: announce_node_context,
        command: AnnounceNode,
    ) -> None:
        ...
