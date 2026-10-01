# Flush the edge's coalesced read times as one event; nothing for an empty batch.
from gen_int.python.procedure.record_blob_access_protocol import record_blob_access_protocol
from gen_int.python.procedure.record_blob_access_context import record_blob_access_context
from gen_def.pydantic.commands import RecordBlobAccess
from gen_def.pydantic.events import BlobAccessRecorded


def record_blob_access(
    context: record_blob_access_context,
    command: RecordBlobAccess,
) -> None:
    if not command.blob_hashes:
        return
    if len(command.blob_hashes) != len(command.last_access_ats):
        raise ValueError("blob_hashes and last_access_ats must be parallel")
    store = context.env.store
    context.emit.blob_access_recorded(BlobAccessRecorded(
        node_id=store.node_id, epoch=store.epoch,
        blob_hashes=list(command.blob_hashes),
        last_access_ats=list(command.last_access_ats),
        occurred_at=command.occurred_at))
