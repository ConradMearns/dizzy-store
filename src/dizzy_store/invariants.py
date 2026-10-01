"""Invariants — laws that must hold after EVERY step of EVERY scenario.

An ordinary claim says "given THESE events, THIS query returns THAT". An
invariant says "no matter what happened, X is true" — so each is checked after
each step, and every hand-written scenario silently tests all of them
(docs/scenario-testing.md, the invariant registry). They are the executable
form of store.feat.yaml's principles, and unlike claims they may read a node's
internals: they test the system's laws, not one example.

Each takes the Runner and returns a list of violation strings (empty = holds).
STEP invariants run after every step; FINAL ones once, at the end of the scenario.
"""
from __future__ import annotations

import random
from pathlib import Path
from queue import SimpleQueue
from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from gen_def.sqla.models import pool as pool_models

Invariant = Callable[["object"], list[str]]


def claims_match_bytes(run) -> list[str]:
    """The log never lies about the disk: every 'present' location under a node's
    CURRENT epoch has its bytes on that node — unless a fault was injected there
    (and scrub has not yet found it)."""
    out = []
    for node in run.cluster.nodes.values():
        rows = (node.session.query(pool_models.BlobLocation)
                .filter(pool_models.BlobLocation.node_id == node.name,
                        pool_models.BlobLocation.epoch == node.epoch,
                        pool_models.BlobLocation.state == "present").all())
        for loc in rows:
            if (node.name, loc.blob_hash) in run.faulted:
                if node.has_blob(loc.blob_hash):
                    run.faulted.discard((node.name, loc.blob_hash))   # repaired: no longer exempt
                continue
            if not node.has_blob(loc.blob_hash):
                out.append(f"{node.name}'s log says it holds {loc.blob_hash[:12]} "
                           "but the bytes are missing or wrong")
    return out


def never_last_copy(run) -> list[str]:
    """Nothing the system DOES destroys the last copy: a blob that had a verified
    copy somewhere before this step still has one after it — unless the step was
    itself data loss (a fault or a wipe, recorded as excused)."""
    out = []
    now = run.copies()
    for blob_hash, before in run.copies_before.items():
        if before and not now.get(blob_hash) and blob_hash not in run.excused:
            out.append(f"the last copy of {blob_hash[:12]} (was on {sorted(before)}) is gone")
    return out


def models_converge(run) -> list[str]:
    """Equal event heads imply equal read models (principle 3: folds converge)."""
    out = []
    names = sorted(run.cluster.nodes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            na, nb = run.cluster.nodes[a], run.cluster.nodes[b]
            if set(na.store.heads()) == set(nb.store.heads()) and len(na.store):
                if _snapshot(na) != _snapshot(nb):
                    out.append(f"{a} and {b} hold the same events but different models")
    return out


def _snapshot(node) -> dict:
    return _snapshot_session(node.session)


def _snapshot_session(session) -> dict:
    snap = {}
    for cls in (pool_models.Node, pool_models.CollectionPolicy, pool_models.Blob,
                pool_models.BlobLocation, pool_models.ScrubState, pool_models.PeerLink):
        rows = session.query(cls).all()
        cols = [c.name for c in cls.__table__.columns]
        snap[cls.__name__] = sorted(tuple(str(getattr(r, c)) for c in cols) for r in rows)
    return snap


def _topological_orders(envelopes, seed: int):
    """The canonical order, and one random valid topological order (parents before
    children) — two different ways the same events could legitimately arrive."""
    by_id = {e.id: e for e in envelopes}
    canonical = list(envelopes)
    children = {i: [] for i in by_id}
    waiting = {}
    for e in envelopes:
        parents = [p for p in e.parents if p in by_id]
        waiting[e.id] = len(parents)
        for p in parents:
            children[p].append(e.id)
    rng = random.Random(seed)
    ready = [i for i, n in waiting.items() if n == 0]
    shuffled = []
    while ready:
        pick = ready.pop(rng.randrange(len(ready)))
        shuffled.append(by_id[pick])
        for c in children[pick]:
            waiting[c] -= 1
            if waiting[c] == 0:
                ready.append(c)
    return canonical, shuffled


def _fold_fresh(node, envelopes, workdir: Path, label: str) -> dict:
    """Fold ``envelopes`` in the given order into a brand-new read-model database."""
    from .node import StoreEnv, StoreTelemetry, build_engine
    from storeutil import ensure_schema_extras
    engine = create_engine(f"sqlite:///{workdir / f'confluence-{label}.db'}", poolclass=NullPool)
    pool_models.metadata.create_all(engine)
    ensure_schema_extras(engine)
    session = Session(engine)
    try:
        _eng, runners = build_engine(session, SimpleQueue(), node.store,
                                     StoreEnv(store=node.env_store, peers=None, disk=None), StoreTelemetry())
        for env in envelopes:
            try:
                event = node.store.reconstruct_event(env)
            except KeyError:
                continue
            for _name, runner in runners.get(type(event), []):
                runner(event, env.ingested_at)
        session.commit()
        return _snapshot_session(session)
    finally:
        session.close()
        engine.dispose()


def confluent_folds(run) -> list[str]:
    """Principle 3 as a law: the same events folded in two different valid orders
    give identical read models. (models-converge only compares nodes whose heads
    happen to be equal; this holds for ANY arrival order, so it catches a fold that
    quietly depends on which event came first.)"""
    if run.cluster is None or not run.cluster.nodes:
        return []
    node = max(run.cluster.nodes.values(), key=lambda n: len(n.store))
    envelopes = list(node.store.iterate())
    if len(envelopes) < 2:
        return []
    canonical, shuffled = _topological_orders(envelopes, seed=len(envelopes))
    workdir = Path(run.workdir)
    a = _fold_fresh(node, canonical, workdir, "a")
    b = _fold_fresh(node, shuffled, workdir, "b")
    if a != b:
        diff = [t for t in a if a[t] != b[t]]
        return [f"folding {len(envelopes)} events in two valid orders gave different {diff}"]
    return []


FINAL_REGISTRY: dict[str, Invariant] = {
    "confluent-folds": confluent_folds,
}

REGISTRY: dict[str, Invariant] = {
    "claims-match-bytes": claims_match_bytes,
    "never-last-copy": never_last_copy,
    "models-converge": models_converge,
}
