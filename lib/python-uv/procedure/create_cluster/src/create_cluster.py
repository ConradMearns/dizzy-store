# Found the cluster. Refuses when this node already belongs to one.
from gen_int.python.procedure.create_cluster_protocol import create_cluster_protocol
from gen_int.python.procedure.create_cluster_context import create_cluster_context
from gen_def.pydantic.commands import CreateCluster
from gen_def.pydantic.events import ClusterCreated


def create_cluster(
    context: create_cluster_context,
    command: CreateCluster,
) -> None:
    store = context.env.store
    if store.cluster_id:
        raise ValueError(f"node {store.node_id} already belongs to cluster {store.cluster_id}")
    context.emit.cluster_created(ClusterCreated(
        cluster_id=command.cluster_id, created_by=store.node_id,
        occurred_at=command.occurred_at))
