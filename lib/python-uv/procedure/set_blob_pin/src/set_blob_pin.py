# Keep (or release) this node's bytes for a blob regardless of pressure.
from gen_int.python.procedure.set_blob_pin_protocol import set_blob_pin_protocol
from gen_int.python.procedure.set_blob_pin_context import set_blob_pin_context
from gen_def.pydantic.commands import SetBlobPin
from gen_def.pydantic.events import BlobPinSet
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput


def set_blob_pin(
    context: set_blob_pin_context,
    command: SetBlobPin,
) -> None:
    store = context.env.store
    replicas = context.query.get_blob_replicas(GetBlobReplicasInput(blob_hash=command.blob_hash))
    for node_id, state, pinned in zip(replicas.node_ids, replicas.states, replicas.pinneds):
        if node_id == store.node_id and state == "present":
            if bool(pinned) == bool(command.pinned):
                return                           # no change
            context.emit.blob_pin_set(BlobPinSet(
                node_id=store.node_id, epoch=store.epoch, blob_hash=command.blob_hash,
                pinned=command.pinned, reason=command.reason,
                occurred_at=command.occurred_at))
            return
    # not held here: nothing to pin
