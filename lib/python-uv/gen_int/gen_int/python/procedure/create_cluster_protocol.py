# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import CreateCluster
from gen_int.python.procedure.create_cluster_context import (
    create_cluster_context,
)


class create_cluster_protocol(Protocol):
    """Refuse when env.store.cluster_id is already set; otherwise emit cluster_created with the command's cluster_id and env.store.node_id as created_by."""

    def __call__(
        self,
        context: create_cluster_context,
        command: CreateCluster,
    ) -> None:
        ...
