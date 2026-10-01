# AUTO-GENERATED — do not edit
from typing import Protocol

from gen_def.pydantic.commands import RecordBlobAccess
from gen_int.python.procedure.record_blob_access_context import (
    record_blob_access_context,
)


class record_blob_access_protocol(Protocol):
    """Emit one blob_access_recorded for the batch; NOTHING for an empty batch."""

    def __call__(
        self,
        context: record_blob_access_context,
        command: RecordBlobAccess,
    ) -> None:
        ...
