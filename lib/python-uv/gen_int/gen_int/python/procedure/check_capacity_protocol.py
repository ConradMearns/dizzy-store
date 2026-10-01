# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import CheckCapacity
from gen_int.python.procedure.check_capacity_context import (
    check_capacity_context,
)


class check_capacity_protocol(Protocol):
    """EFFECT: take two readings — bytes held (get_node_usage) against limit_bytes and the watermarks, and env.disk.free_bytes() against min_free_bytes. Emit space_pressure_detected only when held bytes are above the HIGH watermark OR free space is under the floor, with bytes_to_free the larger of what reaches the LOW watermark and what restores the floor with a quarter of it to spare (hysteresis keeps a node just inside quiet). Reports the readings to progress either way."""

    def __call__(
        self,
        context: check_capacity_context,
        command: CheckCapacity,
    ) -> None:
        ...
