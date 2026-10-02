"""Scenario runner for the store — multi-device, deterministic, data-driven.

Extends the logger's scenario format (scenarios/AUTHORING.md in the logger repo:
`command` / `event` / `claim` steps over one engine) to a CLUSTER of devices.
A scenario is a YAML list of steps, run in order against simulated devices that
run the REAL procedures, projections, queries, policies and DAG replication —
only the network and the clock are simulated. Format: store/scenarios/AUTHORING.md.

After every step the cluster is run to idle (`settle`) and the invariant
registry is checked, so every scenario also tests the system's safety laws.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from storeutil import _SIZE, blob_path
from storeutil import parse_duration as _parse_duration
from storeutil import parse_size as _parse_size

from .invariants import FINAL_REGISTRY, REGISTRY
from .node import StoreNode
from .sim import SimCluster, SimDisk
from .sweep import sweep
from .wiring import GRAPH

DEFAULT_START = "2026-01-01T00:00:00"
CARD_KEYS = {"role", "site", "wants", "location_note", "draining", "endpoints"}
_STEP_KINDS = ("cluster", "at", "sync", "net", "advance", "sweep", "wipe",
               "fault", "announce", "claim", "tree", "edit")


class ScenarioError(Exception):
    """The scenario itself is malformed — reported as a failure, not a crash."""


def parse_size(value: Any) -> int:
    try:
        return _parse_size(value)
    except ValueError as exc:
        raise ScenarioError(str(exc))


def parse_duration(value: Any):
    try:
        return _parse_duration(value)
    except ValueError as exc:
        raise ScenarioError(str(exc))


def _norm(v: Any) -> Any:
    return v.isoformat() if isinstance(v, datetime) else v


def _matches(actual: Any, expected: Any) -> bool:
    a, e = _norm(actual), _norm(expected)
    return a == e or str(a) == str(e)


def _rows(output: dict, keys: list[str]) -> list[dict]:
    lists = {k: output.get(k) for k in keys}
    missing = [k for k, v in lists.items() if not isinstance(v, list)]
    if missing:
        raise ScenarioError(f"query output has no list field(s) {missing}; available: "
                            f"{sorted(k for k, v in output.items() if isinstance(v, list))}")
    n = len(next(iter(lists.values())))
    return [{k: lists[k][i] for k in keys} for i in range(n)]


def _row_count(output: dict) -> int:
    for v in output.values():
        if isinstance(v, list):
            return len(v)
    return 0


class Runner:
    def __init__(self, workdir: Path, frozen, cluster_factory=SimCluster):
        self.workdir = Path(workdir)
        self.frozen = frozen
        self.cluster_factory = cluster_factory
        self.cluster: Optional[SimCluster] = None
        self.fixtures: dict[str, tuple[str, bytes]] = {}      # name -> (sha256, bytes)
        self.dirs: dict[str, Path] = {}                       # tree name -> path
        self.failures: list[str] = []
        self.faulted: set[tuple[str, str]] = set()            # (node, hash) with injected damage
        self.excused: set[str] = set()                        # hashes whose loss THIS step is data loss
        self.copies_before: dict[str, set[str]] = {}
        self.step_no = 0

    # ── helpers ──────────────────────────────────────────────────────────────

    def fail(self, message: str) -> None:
        self.failures.append(f"step {self.step_no}: {message}")

    def node(self, name: str) -> StoreNode:
        if self.cluster is None:
            raise ScenarioError("no cluster declared yet — start with a `cluster:` step")
        if name not in self.cluster.nodes:
            raise ScenarioError(f"unknown device {name!r}; have {sorted(self.cluster.nodes)}")
        return self.cluster.nodes[name]

    def online_node(self, name: str) -> StoreNode:
        node = self.node(name)
        if name in self.cluster.offline:
            raise ScenarioError(f"{name} is offline — a device that is off cannot run commands")
        return node

    def blob_hash(self, name: str) -> str:
        if name not in self.fixtures:
            raise ScenarioError(f"unknown blob fixture ${name} (define it with an `upload:` or `tree:` step)")
        return self.fixtures[name][0]

    def resolve(self, value: Any) -> Any:
        """$name -> that fixture's sha256; $path:name -> a tree's directory."""
        if isinstance(value, str) and value.startswith("$path:"):
            key = value[len("$path:"):]
            if key not in self.dirs:
                raise ScenarioError(f"unknown tree {key!r}")
            return str(self.dirs[key])
        if isinstance(value, str) and value.startswith("$"):
            return self.blob_hash(value[1:])
        if isinstance(value, list):
            return [self.resolve(v) for v in value]
        if isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        return value

    @staticmethod
    def coerce_sizes(cls, fields: dict) -> dict:
        """Scenarios write sizes the way people do (`1MB`); integer fields want ints."""
        out = dict(fields)
        for key, value in fields.items():
            info = cls.model_fields.get(key)
            if info is not None and info.annotation in (int, Optional[int]) \
                    and isinstance(value, str) and _SIZE.match(value):
                out[key] = parse_size(value)
        return out

    @staticmethod
    def fixture_bytes(name: str, size: int) -> bytes:
        return hashlib.shake_256(name.encode()).digest(size)

    def copies(self) -> dict[str, set[str]]:
        """hash -> devices that hold a verified copy RIGHT NOW (the bytes, not the log)."""
        out: dict[str, set[str]] = {}
        if self.cluster is None:
            return out
        from storeutil import iter_blobs
        for node in self.cluster.nodes.values():
            for h, _path, _size in iter_blobs(node.root):
                if node.has_blob(h):
                    out.setdefault(h, set()).add(node.name)
        return out

    # ── steps ────────────────────────────────────────────────────────────────

    def run(self, steps: list) -> None:
        for no, step in enumerate(steps, start=1):
            self.step_no = no
            if not isinstance(step, dict) or not any(k in step for k in _STEP_KINDS):
                self.fail(f"a step must have one of {_STEP_KINDS}, got {step!r}")
                continue
            self.copies_before = self.copies()
            self.excused = set()
            try:
                self.execute(step)
                if self.cluster is not None and "claim" not in step and "advance" not in step:
                    self.cluster.settle()
            except ScenarioError as exc:
                self.fail(str(exc))
                continue
            except Exception as exc:                      # a real failure inside the system
                self.fail(f"{type(exc).__name__}: {exc}")
                continue
            if "claim" not in step:
                for name, check in REGISTRY.items():
                    for violation in check(self):
                        self.fail(f"INVARIANT {name}: {violation}")
        self.step_no = len(steps) + 1
        for name, check in FINAL_REGISTRY.items():
            try:
                for violation in check(self):
                    self.fail(f"INVARIANT {name}: {violation}")
            except Exception as exc:
                self.fail(f"INVARIANT {name} could not run: {type(exc).__name__}: {exc}")

    def execute(self, step: dict) -> None:
        if "cluster" in step:
            return self.do_cluster(step["cluster"])
        if "at" in step:
            return self.do_on(step)
        if "tree" in step:
            return self.do_tree(step["tree"])
        if "sync" in step:
            return self.do_sync(step["sync"])
        if "net" in step:
            return self.do_net(step["net"])
        if "advance" in step:
            text = str(step["advance"]).strip()          # '-10d' moves the clock BACK: a dead RTC
            delta = parse_duration(text.lstrip("-"))
            return self.frozen.tick(-delta if text.startswith("-") else delta)
        if "edit" in step:
            return self.do_edit(step["edit"])
        if "sweep" in step:
            return self.do_sweep(step["sweep"])
        if "wipe" in step:
            return self.do_wipe(step["wipe"])
        if "fault" in step:
            return self.do_fault(step["fault"])
        if "announce" in step:
            return self.do_announce(step["announce"])
        if "claim" in step:
            return self.do_claim(step["claim"])

    def do_cluster(self, spec: dict) -> None:
        if self.cluster is not None:
            raise ScenarioError("a scenario declares its cluster once")
        self.cluster = self.cluster_factory(self.workdir / "devices")
        for index, (name, conf) in enumerate((spec or {}).items()):
            conf = dict(conf or {})
            foreign = conf.pop("cluster_id", None)       # a device of ANOTHER cluster
            card = {k: conf.pop(k) for k in list(conf) if k in CARD_KEYS}
            disk = {k: parse_size(conf.pop(k)) for k in ("disk_capacity", "disk_other") if k in conf}
            config = {k: parse_size(v) if k in ("limit_bytes", "chunk_size", "chunk_threshold_bytes",
                                                "min_free_bytes", "min_evict_bytes") else v for k, v in conf.items()}
            if index == 0:
                node = self.cluster.found(name, card, config)
            else:
                node = self.cluster.add_node(name, card, config, cluster_id=foreign)
            if "disk_capacity" in disk:                       # a filesystem of that size, shared with `disk_other`
                node.disk = SimDisk(node.root, disk["disk_capacity"], disk.get("disk_other", 0))
        for node in self.cluster.nodes.values():
            node.announce()

    def do_on(self, step: dict) -> None:
        node = self.online_node(step["at"])
        if "command" in step:
            name = step["command"]
            if name not in GRAPH.commands:
                raise ScenarioError(f"unknown command {name!r}")
            command = node.make_command(
                name, **self.coerce_sizes(GRAPH.commands[name], self.resolve(step.get("fields") or {})))
            rejects = step.get("expect") == "rejects"
            try:
                node.dispatch(command)
            except Exception as exc:
                if not rejects or not isinstance(exc, ValueError):
                    raise                        # a TypeError is a bug, not a refusal
                return
            if rejects:
                self.fail(f"command {name} on {node.name} was expected to reject but succeeded")
        elif "upload" in step:
            self.do_upload(node, step)
        elif "event" in step:
            name = step["event"]
            cls = GRAPH.events.get(name)
            if cls is None:
                raise ScenarioError(f"unknown event {name!r}")
            node.engine.emit_event(cls(**self.resolve(step.get("fields") or {})))
            node.engine._drain_events()
            node.drain()
        else:
            raise ScenarioError("an `on:` step needs `command`, `upload` or `event`")

    def do_upload(self, node: StoreNode, step: dict) -> None:
        if "count" in step:                       # `upload: "photo-{n}"`, `count: 12`
            for n in range(1, int(step["count"]) + 1):
                self.do_upload(node, {**{k: v for k, v in step.items() if k != "count"},
                                      "upload": step["upload"].format(n=n)})
            return
        name = step["upload"]
        if name not in self.fixtures:
            if "size" not in step:
                raise ScenarioError(f"first upload of {name!r} needs a `size`")
            data = self.fixture_bytes(name, parse_size(step["size"]))
            self.fixtures[name] = (hashlib.sha256(data).hexdigest(), data)
        h, data = self.fixtures[name]
        chunk = parse_size(step["chunk_size"]) if "chunk_size" in step else None
        stored = node.edge_put([data], step.get("collection", "photos"), chunk_size=chunk)
        assert stored == h

    def do_tree(self, spec: dict) -> None:
        """Lay down plain files on a device's disk (no put) for adopt scenarios;
        each file becomes a fixture named `<dir>/<file>`."""
        node = self.node(spec["at"])
        base = self.workdir / "trees" / node.name / spec["dir"]
        layout = spec.get("layout", "tree")               # 'cas': files named by their hash
        truncated = set(spec.get("truncate") or [])       # ... but these hold only half their bytes
        stray = set(spec.get("stray") or [])              # half a file already AT this device's blob address
        for fname, size in (spec.get("files") or {}).items():
            data = self.fixture_bytes(f"{spec['dir']}/{fname}", parse_size(size))
            digest = hashlib.sha256(data).hexdigest()
            path = base / (fname if layout == "tree" else f"{digest[:2]}/{digest[2:4]}/{digest}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data[: len(data) // 2] if fname in truncated else data)
            self.fixtures[f"{spec['dir']}/{fname}"] = (digest, data)
            if fname in stray:
                at = blob_path(node.root, digest)
                at.parent.mkdir(parents=True, exist_ok=True)
                at.write_bytes(data[: len(data) // 2])
        self.dirs[spec["dir"]] = base

    def do_edit(self, spec: dict) -> None:
        """Overwrite the first byte of a tree file IN PLACE (an editor saving over it), or
        with ``unreadable: true`` make it unopenable. If an overwrite also changed a
        device's blob (the two share bytes — a hard link), say so: the invariants must
        then expect that copy to be damaged, as for a fault."""
        self.node(spec["at"])
        key = f"{spec['dir']}/{spec['file']}"
        if key not in self.fixtures or spec["dir"] not in self.dirs:
            raise ScenarioError(f"edit: no tree file {key!r}")
        h = self.fixtures[key][0]
        path = self.dirs[spec["dir"]] / spec["file"]
        if not path.exists():                            # a 'cas' tree names files by their hash
            path = self.dirs[spec["dir"]] / h[:2] / h[2:4] / h
        if spec.get("unreadable"):
            path.chmod(0)                                # exists, cannot be opened
            return
        with open(path, "r+b") as f:                     # in place: same inode, new bytes
            first = f.read(1)
            f.seek(0)
            f.write(bytes([first[0] ^ 0xFF]))
        for other in self.cluster.nodes.values():
            if blob_path(other.root, h).is_file() and not other.has_blob(h):
                self.faulted.add((other.name, h))
                if self.copies_before.get(h) == {other.name}:
                    self.excused.add(h)

    def do_sync(self, spec: Any) -> None:
        if spec == "all":
            names = sorted(self.cluster.nodes)
            for a in names:
                if a in self.cluster.offline:
                    continue
                for b in names:
                    if a != b:
                        self.cluster.nodes[a].run("sync_peer", peer_id=b, direction="both")
            return
        self.online_node(spec["node"]).run(
            "sync_peer", peer_id=spec["peer"], direction=spec.get("direction", "both"))

    def do_net(self, spec: dict) -> None:
        if "offline" in spec:
            self.node(spec["offline"])
            self.cluster.set_offline(spec["offline"], True)
        elif "online" in spec:
            self.node(spec["online"])
            self.cluster.set_offline(spec["online"], False)
        elif "partition" in spec:
            self.cluster.partition(spec["partition"])
        elif spec.get("heal"):
            self.cluster.heal()
        else:
            raise ScenarioError(f"net needs offline / online / partition / heal, got {spec!r}")

    def do_sweep(self, target: Any) -> None:
        names = sorted(self.cluster.nodes) if target == "all" else [target]
        for name in names:
            if name not in self.cluster.offline:
                sweep(self.node(name))

    def do_wipe(self, name: str) -> None:
        node = self.node(name)
        for h, holders in self.copies_before.items():
            if holders == {name}:
                self.excused.add(h)                       # wiping the SOLE holder IS data loss, by design
        self.faulted = {(n, h) for n, h in self.faulted if n != name}
        node.wipe()

    def do_fault(self, spec: dict) -> None:
        node = self.node(spec["at"])
        if "corrupt" in spec or "remove" in spec or "unreadable" in spec:
            h = self.resolve(spec.get("corrupt") or spec.get("remove") or spec.get("unreadable"))
            path = blob_path(node.root, h)
            if not path.is_file():
                raise ScenarioError(f"{node.name} has no file for {h[:12]} to damage")
            if "corrupt" in spec:
                data = bytearray(path.read_bytes())       # same size, flipped bytes
                every = parse_size(spec["every"]) if "every" in spec else len(data) or 1
                for offset in range(0, len(data), every):  # `every: 1KB` damages each 1 KB block
                    data[offset] ^= 0xFF
                path.write_bytes(bytes(data))
            elif "unreadable" in spec:
                path.chmod(0)                             # exists, but cannot be opened (an I/O-error stand-in)
            else:
                path.unlink()
            self.faulted.add((node.name, h))
            if self.copies_before.get(h) == {node.name}:
                self.excused.add(h)                       # damaging the SOLE copy IS data loss, by design
        else:
            raise ScenarioError(f"fault needs corrupt, remove or unreadable, got {spec!r}")

    def do_announce(self, spec: Any) -> None:
        name, overrides = (spec, {}) if isinstance(spec, str) else (
            spec["node"], {k: v for k, v in spec.items() if k != "node"})
        self.online_node(name).announce(**overrides)

    # ── claims ───────────────────────────────────────────────────────────────

    def do_claim(self, spec: dict) -> None:
        node = self.node(spec["at"]) if "at" in spec else self._only_node()
        if "blob" in spec:
            h = self.resolve(spec["blob"])
            want = bool(spec.get("has", True))
            got = node.has_blob(h)
            if got != want:
                self.fail(f"{node.name}.has({spec['blob']}) is {got}, expected {want}")
            return
        if "query" not in spec:
            raise ScenarioError("a claim needs `query` (or `blob` + `has`)")
        name = spec["query"]
        if name not in GRAPH.names("queries"):
            raise ScenarioError(f"unknown query {name!r}")
        output = node.query(name, **self.resolve(spec.get("input") or {})).model_dump()
        for problem in self.check_expect(name, output, self.resolve(spec.get("expect"))):
            self.fail(f"on {node.name}: {problem}")

    def _only_node(self) -> StoreNode:
        if self.cluster is None or len(self.cluster.nodes) != 1:
            raise ScenarioError("a claim names the device it asks (`on:`)")
        return next(iter(self.cluster.nodes.values()))

    @staticmethod
    def check_expect(name: str, output: dict, expect: Any) -> list[str]:
        if expect is None:
            return [f"claim on {name} has no expect"]
        if isinstance(expect, str):
            expect = {expect: True}
        problems: list[str] = []
        if expect.get("empty"):
            if _row_count(output):
                problems.append(f"{name} expected empty, got {_row_count(output)} rows")
            return problems
        if "count" in expect and _row_count(output) != expect["count"]:
            problems.append(f"{name} expected count {expect['count']}, got {_row_count(output)}")
        if "equals" in expect:
            got = {k: output.get(k) for k in expect["equals"]}
            if not all(_matches(got[k], v) for k, v in expect["equals"].items()):
                problems.append(f"{name} expected {expect['equals']}, got {got}")
        for want in expect.get("contains", []):
            rows = _rows(output, list(want))
            if not any(all(_matches(r[k], want[k]) for k in want) for r in rows):
                problems.append(f"{name} has no row matching {want} — rows seen: {rows[:10]}")
        for bad in expect.get("not_contains", []):
            rows = _rows(output, list(bad))
            hit = [r for r in rows if all(_matches(r[k], bad[k]) for k in bad)]
            if hit:
                problems.append(f"{name} must not contain {bad}, but found {hit[0]}")
        return problems


def run_scenario(path: Path, workdir: Path, cluster_factory=SimCluster) -> list[str]:
    """Run one scenario file; return its failures (empty = it holds). The cluster
    factory chooses the transport: SimCluster (in-process) or HttpCluster (real HTTP)."""
    steps = yaml.safe_load(Path(path).read_text())
    if not isinstance(steps, list) or not steps:
        return ["scenario.yaml must be a non-empty list of steps"]
    start = DEFAULT_START
    if isinstance(steps[0], dict) and "time" in steps[0]:
        start = steps.pop(0)["time"]
    from freezegun import freeze_time        # a TEST-time dependency: never imported by the daemon

    with freeze_time(start, real_asyncio=True) as frozen:     # asyncio keeps real time (uvicorn)
        runner = Runner(workdir, frozen, cluster_factory)
        try:
            runner.run(steps)
        finally:
            if runner.cluster is not None:
                runner.cluster.close()
    return runner.failures
