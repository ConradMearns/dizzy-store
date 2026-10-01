# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import SetBlobPin
from gen_int.python.procedure.set_blob_pin_context import (
    set_blob_pin_context,
)


class set_blob_pin_protocol(Protocol):
    """Emit blob_pin_set when it changes the pin state of a blob this node holds (get_blob_replicas); nothing otherwise."""

    def __call__(
        self,
        context: set_blob_pin_context,
        command: SetBlobPin,
    ) -> None:
        ...
