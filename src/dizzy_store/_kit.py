"""Where the runtime kit lives TODAY.

The engine, the content-addressed event store and the anti-entropy replicator
are the logger's host/ modules (their extraction into DIZZY is seeds dizzy-eea5 /
dizzy-ffdc). This feature's own generated library and element packages live under
store/lib/python-uv. This file is the ONLY place that knows either location —
when the kit moves into DIZZY, only these imports change.
"""
from __future__ import annotations

import sys
from pathlib import Path

STORE_ROOT = Path(__file__).resolve().parents[2]            # store/
REPO_ROOT = STORE_ROOT.parent
LIB = STORE_ROOT / "lib" / "python-uv"
FEAT_PATH = STORE_ROOT / "store.feat.yaml"


def _add(path: Path) -> None:
    p = str(path)
    if p not in sys.path:
        sys.path.append(p)      # append: never shadow anything already resolved


_add(LIB)                                                    # storeutil
for _kind in ("procedure", "projection", "query", "policy"):
    for _src in sorted((LIB / _kind).glob("*/src")):
        _add(_src)                                           # each element's module
_add(REPO_ROOT / "host")                                     # engine, store, replicate

from engine import Engine, IngestedAtAdapter                 # noqa: E402
from replicate import fold_envelopes, pull                   # noqa: E402
from store import EventStore                                 # noqa: E402  (host/store.py)

__all__ = ["Engine", "IngestedAtAdapter", "EventStore", "fold_envelopes", "pull",
           "STORE_ROOT", "FEAT_PATH", "LIB"]
