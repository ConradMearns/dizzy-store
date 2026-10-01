# Record a blob the edge has ALREADY written under this node's root. Idempotent.
from gen_int.python.procedure.put_blob_protocol import put_blob_protocol
from gen_int.python.procedure.put_blob_context import put_blob_context
from gen_def.pydantic.commands import PutBlob
from gen_def.pydantic.events import BlobRegistered, BlobStored
from gen_def.pydantic.query.get_blob import GetBlobInput
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput
from storeutil import blob_path, valid_recipe


def put_blob(
    context: put_blob_context,
    command: PutBlob,
) -> None:
    store = context.env.store
    path = blob_path(store.root, command.blob_hash)            # refuses anything that is not a sha256
    replicas = context.query.get_blob_replicas(GetBlobReplicasInput(blob_hash=command.blob_hash))
    for node_id, state in zip(replicas.node_ids, replicas.states):
        if node_id == store.node_id and state == "present":
            return                               # re-uploads are routine: nothing new
    if command.chunk_hashes or command.chunk_size:
        if not valid_recipe(command.byte_size, command.chunk_size, list(command.chunk_hashes or [])):
            raise ValueError("chunk recipe could never be used: need chunk_size > 0 and "
                             "ceil(byte_size / chunk_size) sha256 hashes")
    if not path.is_file() or path.stat().st_size != command.byte_size:
        raise ValueError(
            f"blob {command.blob_hash[:12]} is not under root at the declared size — "
            "the edge writes the bytes first, then dispatches put_blob")
    blob = context.query.get_blob(GetBlobInput(blob_hash=command.blob_hash))
    if not blob.found:
        context.emit.blob_registered(BlobRegistered(
            blob_hash=command.blob_hash, byte_size=command.byte_size,
            collection=command.collection, chunk_size=command.chunk_size,
            chunk_hashes=list(command.chunk_hashes) if command.chunk_hashes else None,
            occurred_at=command.occurred_at))
    context.emit.blob_stored(BlobStored(
        node_id=store.node_id, epoch=store.epoch, blob_hash=command.blob_hash,
        source="upload", occurred_at=command.occurred_at))
