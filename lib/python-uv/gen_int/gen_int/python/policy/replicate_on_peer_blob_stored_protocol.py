# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.events import BlobStored
from gen_int.python.policy.replicate_on_peer_blob_stored_context import (
    replicate_on_peer_blob_stored_context,
)


class replicate_on_peer_blob_stored_protocol(Protocol):
    """When a PEER stores a blob (blob_stored for another node_id), dispatch replicate_blob (reason 'replica') if this node wants it: not draining (get_node_profile), the blob's collection (get_blob) is in its wants, and it does not already hold it (get_blob_replicas). Fresh facts only — older ones are the sweep's job, as is a blob whose blob_registered has not merged yet (get_blob finds nothing). This is the whole "push": a node that stores something says so, and every interested peer reacts."""

    def __call__(
        self,
        event: BlobStored,
        context: replicate_on_peer_blob_stored_context,
    ) -> None:
        ...
