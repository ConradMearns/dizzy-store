"""Wiring — register the feature's elements into the control-loop Engine.

The logger hand-mirrors every element into wiring.py (seed dizzy-07fb: generate
it). This feature's wiring is DERIVED instead: store.feat.yaml names every
element, DIZZY's naming convention locates its module and generated context, and
the context dataclass's own fields say what to inject (emit / query / env /
telemetry). Adding an element to the feat needs no change here.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, fields
from types import SimpleNamespace
from typing import Any, Callable, Optional

from dizzy.engine import FeatGraph

from . import _kit
from ._kit import Engine, IngestedAtAdapter
from gen_int.python.adapters.sqla import SqlaAdapter

GRAPH = FeatGraph.load(_kit.FEAT_PATH)


@dataclass
class StoreEnv:
    """The feat's ``environment`` section, hydrated: ``store`` (config), ``peers`` (the
    transport client) and ``disk`` (the filesystem's free space) — the last two are
    duck-typed and host-implemented."""
    store: Any
    peers: Any
    disk: Any


@dataclass
class StoreTelemetry:
    """The feat's ``telemetry`` sinks — host callables, never events."""
    progress: Callable[[Any], None] = lambda payload: None
    transfer_progress: Callable[[Any], None] = lambda payload: None
    peer_health: Callable[[Any], None] = lambda payload: None


def _element(name: str):
    """Element function by convention: module and function share the feat name."""
    return getattr(importlib.import_module(name), name)


# Where DIZZY's generator puts each kind's context class (module naming differs).
_CONTEXT_MODULE = {
    "procedure": "gen_int.python.procedure.{name}_context",
    "policy": "gen_int.python.policy.{name}_context",
    "projection": "gen_int.python.projection.{name}_projection",
    "query": "gen_int.python.query.{name}",
}


def _context_class(kind: str, name: str):
    module = importlib.import_module(_CONTEXT_MODULE[kind].format(name=name))
    return getattr(module, f"{name}_context")


def build_queries(session) -> SimpleNamespace:
    """Every feat query as ``queries.<name>(Input) -> Output`` bound to a session."""
    adapter = SqlaAdapter(session=session)
    out = {}
    for name in GRAPH.names("queries"):
        fn, ctx_cls = _element(name), _context_class("query", name)
        out[name] = (lambda i, fn=fn, ctx_cls=ctx_cls: fn(i, ctx_cls(adapter=adapter)))
    return SimpleNamespace(**out)


def _inject(ctx_cls, *, emit: Callable, queries, env: StoreEnv, telemetry: StoreTelemetry):
    """Build one element's context from the dataclass's own declared fields."""
    parts = {}
    for f in fields(ctx_cls):
        if f.name == "attempt":
            continue          # newer generators add the engine's idempotency key; these elements
                              # make themselves idempotent by checking the read models first
        section = f.type
        names = [g.name for g in fields(section)]
        if f.name == "emit":
            parts["emit"] = section(**{n: emit for n in names})
        elif f.name == "query":
            parts["query"] = section(**{n: getattr(queries, n) for n in names})
        elif f.name == "env":
            parts["env"] = section(**{n: getattr(env, n) for n in names})
        elif f.name == "telemetry":
            parts["telemetry"] = section(**{n: getattr(telemetry, n) for n in names})
        else:
            raise RuntimeError(f"unexpected context field {f.name!r} in {ctx_cls.__name__}")
    return ctx_cls(**parts)


def build_engine(session, command_queue, store, env: StoreEnv,
                 telemetry: Optional[StoreTelemetry] = None,
                 observer: Optional[Callable[[str, Any], None]] = None):
    """Register every element into a fresh Engine bound to one session.

    Returns ``(engine, projection_runners)``: the runners (event class ->
    [(name, runner)]) are what fold-on-replicate feeds merged events through, so
    a replicated fact folds by exactly the code a local emit does."""
    telemetry = telemetry or StoreTelemetry()
    eng = Engine(command_queue, store, observer=observer, commit=session.commit)
    queries = build_queries(session)
    commands, events = GRAPH.commands, GRAPH.events

    for name in GRAPH.names("procedures"):
        spec = GRAPH.entry("procedures", name)
        fn, ctx_cls = _element(name), _context_class("procedure", name)
        eng.register_procedure(
            commands[spec["command"]],
            lambda c, fn=fn, ctx_cls=ctx_cls: fn(
                _inject(ctx_cls, emit=eng.emit_event, queries=queries, env=env,
                        telemetry=telemetry), c),
            name=name)

    for name in GRAPH.names("policies"):
        spec = GRAPH.entry("policies", name)
        fn, ctx_cls = _element(name), _context_class("policy", name)
        eng.register_policy(
            events[spec["event"]],
            lambda e, fn=fn, ctx_cls=ctx_cls: fn(
                e, _inject(ctx_cls, emit=eng.dispatch_command, queries=queries, env=env,
                           telemetry=telemetry)),
            name=name)

    runners: dict[type, list] = {}
    for name in GRAPH.names("projections"):
        spec = GRAPH.entry("projections", name)
        fn, ctx_cls = _element(name), _context_class("projection", name)
        runner = (lambda e, ingested_at, fn=fn, ctx_cls=ctx_cls: fn(
            e, ctx_cls(adapter=IngestedAtAdapter(session=session, ingested_at=ingested_at))))
        eng.register_projection(events[spec["event"]], runner, name=name)
        runners.setdefault(events[spec["event"]], []).append((name, runner))
    return eng, runners


def registered(engine: Engine) -> dict[str, set[str]]:
    """What an engine actually has wired, keyed like ``GRAPH.validate_registered``."""
    return {
        "procedures": {n for n, _ in engine._procedures.values()},
        "policies": {n for lst in engine._policies.values() for n, _ in lst},
        "projections": {n for lst in engine._projections.values() for n, _ in lst},
    }


def validate_against_feat(engine: Engine) -> None:
    GRAPH.validate_registered(registered(engine))
