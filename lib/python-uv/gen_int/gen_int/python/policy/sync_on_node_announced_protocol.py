# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.events import NodeAnnounced
from gen_int.python.policy.sync_on_node_announced_context import (
    sync_on_node_announced_context,
)


class sync_on_node_announced_protocol(Protocol):
    """When a PEER announces itself (a fresh node_announced for another node_id), dispatch sync_peer direction 'both' — joining the pool is being announced, then syncing. Idempotent: a re-announcement costs one digest exchange."""

    def __call__(
        self,
        event: NodeAnnounced,
        context: sync_on_node_announced_context,
    ) -> None:
        ...
