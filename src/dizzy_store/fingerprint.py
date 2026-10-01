"""What a read model's CONTENT depends on — so an update can never leave one stale.

The log is the truth and the read models (models.db) are a fold of it. A fold is a function of
the schema it fills, the events that feed it, the projections that do the folding and the helpers
they share. Change any of those — a `git pull` is all it takes, the install is editable — and a
database built by the OLD code may not be what the NEW code would build. So the node stamps the
database with this fingerprint, and a start that finds a different one throws the models away
(tables and all, so a new column is no problem) and folds the log again. A few seconds, once per
update; the alternative is a store that quietly disagrees with its own history.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import _kit


def readmodel_files() -> list[Path]:
    import gen_def.pydantic.events as events
    import gen_def.sqla.models.pool as models
    import storeutil
    files = [Path(models.__file__), Path(events.__file__), Path(storeutil.__file__)]
    files += sorted((_kit.LIB / "projection").glob("*/src/*.py"))
    return files


def readmodel_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in readmodel_files():
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()
