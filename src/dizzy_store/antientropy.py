"""Batched anti-entropy: set reconciliation over the event DAG's id set.

host/replicate.pull walks a peer's ancestry one event per round trip — fine
in-process, hopeless over a network for a 30,000-event log (a linear chain
discovers each parent only after fetching its child). Here the two sides compare
256 bucket digests (event ids grouped by their first two hex characters), fetch
the ids of ONLY the buckets that differ, and fetch the missing events in
batches. Then host/replicate.pull — unchanged — orders them parents-first,
verifies every content hash and adds them, so the correctness kernel (hash
verification, parents-first, idempotent add) stays the DAG store's.

A steady-state sync with nothing new costs one ~10 KB digest exchange; a wiped
device's first sync costs the whole log in batches of ``BATCH`` events.

The "remote" is anything with ``buckets()``, ``ids(prefixes)`` and
``events(ids)`` — the in-process PeerSurface (simulation) or the HTTP client
(real devices), so both transports run THIS algorithm.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Iterable

from dagstore import Event

from ._kit import pull

BATCH = 200


def bucket_digests(store) -> dict[str, str]:
    """{two-hex prefix: sha256 of the sorted ids in that bucket}, non-empty
    buckets only. Equal digests mean the two sides hold the same ids there."""
    with store._lock:
        ids = store.dag.ids()
    buckets: dict[str, list[str]] = defaultdict(list)
    for event_id in ids:
        buckets[event_id[:2]].append(event_id)
    return {prefix: hashlib.sha256("\n".join(sorted(members)).encode()).hexdigest()
            for prefix, members in buckets.items()}


def ids_in_buckets(store, prefixes: Iterable[str]) -> list[str]:
    wanted = set(prefixes)
    with store._lock:
        ids = store.dag.ids()
    return sorted(i for i in ids if i[:2] in wanted)


def events_by_id(store, ids: Iterable[str]) -> list[Event]:
    out = []
    with store._lock:
        for event_id in ids:
            try:
                out.append(store.dag.get(event_id))
            except KeyError:
                continue          # not held here: the caller will not receive it
    return out


def reconcile_pull(local, remote, batch: int = BATCH) -> list:
    """Pull everything ``remote`` has that ``local`` lacks. Returns the new
    envelopes in delivery order (parents first), exactly as ``replicate.pull``
    does, ready for fold-on-replicate."""
    mine = bucket_digests(local)
    theirs = remote.buckets()
    differing = sorted(b for b, digest in theirs.items() if mine.get(b) != digest)
    if not differing:
        return []
    with local._lock:
        have = local.dag.ids()
    missing = [i for i in remote.ids(differing) if i not in have]
    if not missing:
        return []
    fetched: dict[str, Event] = {}
    for start in range(0, len(missing), batch):
        for event in remote.events(missing[start:start + batch]):
            fetched[event.id] = event

    def fetch_event(event_id: str) -> Event:
        if event_id not in fetched:          # a parent outside the bucket diff
            for event in remote.events([event_id]):
                fetched[event.id] = event
        return fetched[event_id]

    return pull(local, lambda: list(fetched), fetch_event)
