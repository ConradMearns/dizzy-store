# Two readings — bytes held against the limit, free space against the floor — and one
# rule (storeutil.capacity_pressure) deciding whether that is pressure. Emits only when
# it is: hysteresis keeps a node just inside both limits quiet.
from gen_int.python.procedure.check_capacity_protocol import check_capacity_protocol
from gen_int.python.procedure.check_capacity_context import check_capacity_context
from gen_def.pydantic.commands import CheckCapacity
from gen_def.pydantic.events import SpacePressureDetected
from gen_def.pydantic.query.get_node_usage import GetNodeUsageInput
from gen_def.pydantic.telemetry import Progress
from storeutil import capacity_pressure


def check_capacity(
    context: check_capacity_context,
    command: CheckCapacity,
) -> None:
    store = context.env.store
    held = context.query.get_node_usage(GetNodeUsageInput(node_id=store.node_id)).held_bytes
    free = context.env.disk.free_bytes()
    context.telemetry.progress(Progress(
        stage="capacity",
        detail=f"{held} of {store.limit_bytes} bytes held; {free} free on the disk"))
    to_free = capacity_pressure(held, free, store)
    if to_free:
        context.emit.space_pressure_detected(SpacePressureDetected(
            node_id=store.node_id, used_bytes=held, limit_bytes=store.limit_bytes,
            free_bytes=free, bytes_to_free=to_free, occurred_at=command.occurred_at))
