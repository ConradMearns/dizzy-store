# A PEER stored a blob -> dispatch replicate_blob if this node wants it. This is
# the whole "push": a node that stores something says so, and every interested
# peer reacts. Fresh facts only; older ones (and a blob whose blob_registered has
# not merged yet) are the host sweep's job.
from gen_int.python.policy.replicate_on_peer_blob_stored_protocol import replicate_on_peer_blob_stored_protocol
from gen_int.python.policy.replicate_on_peer_blob_stored_context import replicate_on_peer_blob_stored_context
from gen_def.pydantic.events import BlobStored
from gen_def.pydantic.commands import ReplicateBlob
from gen_def.pydantic.query.get_node_profile import GetNodeProfileInput
from gen_def.pydantic.query.get_blob import GetBlobInput
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput
from storeutil import is_fresh, now_utc


def replicate_on_peer_blob_stored(
    event: BlobStored,
    context: replicate_on_peer_blob_stored_context,
) -> None:
    store = context.env.store
    if event.node_id == store.node_id:
        return                                   # my own fact — not a request
    if not is_fresh(event.occurred_at, store.live_window_s):
        return                                   # history, not news: the sweep's job
    me = context.query.get_node_profile(GetNodeProfileInput(node_id=store.node_id))
    if not me.found or me.draining:
        return                                   # unannounced, or leaving the pool
    blob = context.query.get_blob(GetBlobInput(blob_hash=event.blob_hash))
    if not blob.found:
        return                                   # blob_registered not merged yet
    wants = list(me.wants or [])
    if "*" not in wants and blob.collection not in wants:
        return
    replicas = context.query.get_blob_replicas(GetBlobReplicasInput(blob_hash=event.blob_hash))
    for node_id, state in zip(replicas.node_ids, replicas.states):
        if node_id == store.node_id and state == "present":
            return                               # already hold it
    context.emit.replicate_blob(ReplicateBlob(
        blob_hash=event.blob_hash, from_node=event.node_id,
        reason="replica", occurred_at=now_utc()))
