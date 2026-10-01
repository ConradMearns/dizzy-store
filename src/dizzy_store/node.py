"""One device: event store + read models + blob root + engine.

A StoreNode is everything one machine is in the feat's terms. It is transport-
agnostic: the peers client (how it reaches other devices) is attached after
construction — the simulation attaches an in-process one, the daemon an HTTP one.
The same class runs in scenarios and for real.

Threading: the engine and the read-model session are single-threaded — whoever
runs commands (the daemon's loop, its admin API) must hold the daemon's lock.
Only the PeerSurface is meant to be called from other threads: it touches the
event store (locked) and plain files, never the session.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import threading
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Any, Iterable, Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from . import _kit  # noqa: F401  (side effect: sys.path for the runtime kit)
from ._kit import EventStore, fold_envelopes
from .antientropy import bucket_digests, events_by_id, ids_in_buckets, reconcile_pull
from .fingerprint import readmodel_fingerprint
from .wiring import GRAPH, StoreEnv, StoreTelemetry, build_engine, build_queries
from dizzy.engine import camel_case
from gen_def.pydantic.environment import Store
from gen_def.pydantic.telemetry import Progress
from gen_def.sqla.models import pool as pool_models
from storeutil import (NotAStore, OutOfSpace, PeerUnreachable, RootVanished, blob_path,
                       ensure_schema_extras, ensure_state_table, free_bytes, get_flag,
                       place_atomic, read_flag, set_flag, sha256_file)

# What env.store gets unless a node (or scenario) overrides it.
DEFAULT_CONFIG = dict(
    limit_bytes=10**9, high_watermark=0.9, low_watermark=0.7,
    live_window_s=3600, max_dispatch_per_event=10,
    max_bytes_per_sec=0, scrub_bytes_per_sec=0, min_free_bytes=0,
    chunk_threshold_bytes=64 * 1024 * 1024, chunk_size=16 * 1024 * 1024)

DEFAULT_CARD = dict(role="archive", site="home", wants=["*"], location_note=None,
                    draining=False, endpoints=[])

TELEMETRY_KEEP = 2000        # observation buffers are bounded: a daemon runs for months
CARD_KEYS = ("role", "site", "location_note", "wants", "draining", "endpoints")
DIRTY = "folds_incomplete"   # StoreState flag: a fold may be half done — rebuild on start
FINGERPRINT = "readmodel_fingerprint"   # StoreState: what code and schema built the read models


class NoPeers:
    """The peers client of a device with no network: every call is unreachable."""

    def __getattr__(self, name):
        def unreachable(*_a, **_k):
            raise PeerUnreachable("no network attached")
        return unreachable


class RealDisk:
    """The filesystem under a device's root, as env.disk: what an ordinary writer can still add."""

    def __init__(self, root: Path):
        self._root = root

    def free_bytes(self) -> int:
        return free_bytes(self._root)


class _DiskProxy:
    """Late-bound like the peers: procedures hold this; a scenario can swap node.disk."""

    def __init__(self, node: "StoreNode"):
        self._node = node

    def free_bytes(self) -> int:
        return self._node.disk.free_bytes()


class _PeersProxy:
    """Late-bound: procedures hold this; the node points it at the real client."""

    def __init__(self, node: "StoreNode"):
        self._node = node

    def __getattr__(self, name):
        return getattr(self._node.peers, name)


class PeerSurface:
    """What a device offers other devices — the peer API, in-process form. The
    HTTP router serves exactly these calls, so both transports share one meaning."""

    def __init__(self, node: "StoreNode"):
        self._node = node

    def cluster_id(self) -> Optional[str]:
        return self._node.env_store.cluster_id

    # anti-entropy (antientropy.reconcile_pull speaks to these three)
    def buckets(self) -> dict:
        return bucket_digests(self._node.store)

    def ids(self, prefixes) -> list[str]:
        return ids_in_buckets(self._node.store, prefixes)

    def events(self, ids) -> list:
        return events_by_id(self._node.store, ids)

    # blobs
    def blob_size(self, blob_hash: str) -> Optional[int]:
        path = blob_path(self._node.root, blob_hash)
        return path.stat().st_size if path.is_file() else None

    def verify_blob(self, blob_hash: str) -> dict:
        """PROVE this device holds the exact bytes right now: re-hash the file. Also
        reports the device's LIVE role and draining state — not what its log said
        last week. evict_blob asks this of every peer it would rely on: a size match
        is not proof, and a peer that is itself leaving does not count."""
        path = blob_path(self._node.root, blob_hash)
        card = self._node.card
        live = {"role": card.get("role"), "draining": bool(card.get("draining"))}
        if not path.is_file():
            return {"held": False, "size": None, **live}
        try:
            held = sha256_file(path) == blob_hash
        except OSError:
            held = False
        return {"held": held, "size": path.stat().st_size, **live}

    def read_blob(self, blob_hash: str, offset: int = 0,
                  length: Optional[int] = None, bufsize: int = 1 << 16) -> Iterator[bytes]:
        path = blob_path(self._node.root, blob_hash)
        if not path.is_file():
            raise PeerUnreachable(f"{self._node.name} does not hold {blob_hash[:12]}")
        with open(path, "rb") as f:
            f.seek(offset)
            remaining = length
            while remaining is None or remaining > 0:
                piece = f.read(bufsize if remaining is None else min(bufsize, remaining))
                if not piece:
                    return
                if remaining is not None:
                    remaining -= len(piece)
                yield piece

    def request_pull(self, requester: str, endpoints: Optional[list[str]] = None) -> None:
        """'Push': the requester asks this device to pull from it. A notification
        only — the device acts on it on its own next turn, as a real peer would."""
        self._node.note_pull_request(requester, endpoints)


class StagedBlob:
    """An upload in flight: bytes stream into a temp file while their sha256 — and
    the sha256 of each fixed-size chunk — accumulate, so a file of any size is
    hashed in one pass without being held in memory."""

    def __init__(self, path: Path, chunk_size: int, forced: bool):
        self.path, self.chunk_size, self.forced = path, chunk_size, forced
        self.size = 0
        self.chunk_hashes: list[str] = []
        self._file = open(path, "wb")
        self._whole = hashlib.sha256()
        self._chunk = hashlib.sha256()
        self._chunk_len = 0

    def write(self, data: bytes) -> None:
        self._file.write(data)
        self._whole.update(data)
        self.size += len(data)
        view = memoryview(data)
        while len(view):
            take = min(len(view), self.chunk_size - self._chunk_len)
            self._chunk.update(view[:take])
            self._chunk_len += take
            view = view[take:]
            if self._chunk_len == self.chunk_size:
                self.chunk_hashes.append(self._chunk.hexdigest())
                self._chunk, self._chunk_len = hashlib.sha256(), 0

    def finish(self) -> str:
        self._file.close()
        if self._chunk_len:
            self.chunk_hashes.append(self._chunk.hexdigest())
            self._chunk, self._chunk_len = hashlib.sha256(), 0
        return self._whole.hexdigest()

    def abort(self) -> None:
        self._file.close()
        self.path.unlink(missing_ok=True)


class StoreNode:
    def __init__(self, name: str, root: str | Path, *, cluster_id: Optional[str],
                 card: Optional[dict] = None, config: Optional[dict] = None,
                 epoch: Optional[str] = None, life: int = 1, create_root: bool = True):
        self.name = name
        self.root = Path(root)
        self._create_root = create_root          # False for a real device: its root must already BE a store
        self.cluster_id = cluster_id
        self.card = {**DEFAULT_CARD, **(card or {})}
        if "wants" not in (card or {}):          # a hot cache wants nothing in full; archives and drives want all
            self.card["wants"] = [] if self.card["role"] == "hot" else ["*"]
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.life = life
        self._epoch = epoch
        self.peers: Any = NoPeers()
        self.disk: Any = RealDisk(self.root)
        self._pull_requests: list[str] = []
        self._pull_lock = threading.Lock()
        self._access: dict[str, datetime] = {}
        self._access_lock = threading.Lock()
        self.sweep_state: dict = {}              # (kind, blob_hash) -> (failures, retry_after)
        self._unsafe_depth = 0                   # nesting of operations that may half-fold
        self._unsafe_failed = False
        self.progress: deque = deque(maxlen=TELEMETRY_KEEP)
        self.progress_total = 0          # monotonic: a bounded deque cannot be indexed by position
        self.peer_health: deque = deque(maxlen=TELEMETRY_KEEP)
        self.transfers: deque = deque(maxlen=TELEMETRY_KEEP)
        self._start()

    # ── lifecycle ────────────────────────────────────────────────────────────

    @property
    def epoch(self) -> str:
        return self._epoch or f"{self.name}-{self.life}"

    def _start(self) -> None:
        state = self.root / ".store"
        if self._create_root:
            for d in (self.root, state, state / "tmp", state / "quarantine"):
                d.mkdir(parents=True, exist_ok=True)
        else:                                    # a real device never conjures its own root
            if not state.is_dir():
                raise NotAStore(f"{self.root} is not a store device (no {state}) — "
                                "is its drive mounted?")
            for d in (state / "tmp", state / "quarantine"):
                d.mkdir(exist_ok=True)
        st = os.stat(state)
        self._root_id = (st.st_dev, st.st_ino)   # what guard_root compares against
        self.env_store = Store(
            node_id=self.name, cluster_id=self.cluster_id, epoch=self.epoch,
            root=str(self.root), state_dir=str(state), tmp_dir=str(state / "tmp"),
            quarantine_dir=str(state / "quarantine"), **self.config)
        self.store = EventStore(state / "events.db", event_classes=GRAPH.events)
        self.sqla = create_engine(f"sqlite:///{state / 'models.db'}", poolclass=NullPool)
        # Decide whether the read models can be trusted BEFORE touching them: a database built by
        # other code may have tables of another shape, and nothing may be created on top of those.
        self.fingerprint = readmodel_fingerprint()
        ensure_state_table(self.sqla)
        stored = read_flag(self.sqla, FINGERPRINT)
        brand_new = stored is None and len(self.store) == 0
        stale = not brand_new and stored != self.fingerprint
        if stale:
            pool_models.metadata.drop_all(self.sqla)     # derived data: the log can always refill it
        pool_models.metadata.create_all(self.sqla)
        ensure_schema_extras(self.sqla)
        self.session = Session(self.sqla)
        self.command_queue: SimpleQueue = SimpleQueue()
        telemetry = StoreTelemetry(
            progress=self._on_progress, peer_health=self.peer_health.append,
            transfer_progress=self.transfers.append)
        self.engine, self.runners = build_engine(
            self.session, self.command_queue, self.store,
            StoreEnv(store=self.env_store, peers=_PeersProxy(self), disk=_DiskProxy(self)),
            telemetry)
        self.queries = build_queries(self.session)
        self.surface = PeerSurface(self)
        if stale:
            self.rebuild("the code or schema changed")   # an update: refill the fresh tables from the log
        elif get_flag(self.session, DIRTY) == "1":
            self.rebuild("the last run died mid-fold")
        set_flag(self.session, FINGERPRINT, self.fingerprint)

    def rebuild(self, why: str = "") -> int:
        """Throw the read models away and fold the whole log again, in canonical
        order. The log is the truth and every fold is deterministic, so this always
        works; it is how a crash between "events appended" and "events folded"
        heals, and how an update that changed the schema or the folds takes effect
        (start-up drops the tables first then). Returns events folded."""
        for cls in (pool_models.Node, pool_models.CollectionPolicy, pool_models.Blob,
                    pool_models.BlobLocation, pool_models.ScrubState, pool_models.PeerLink):
            self.session.query(cls).delete()
        self.session.commit()
        folded = 0
        for envelope in self.store.iterate():
            try:
                event = self.store.reconstruct_event(envelope)
            except KeyError:
                continue                         # a retired event type: the fact stands
            for _name, runner in self.runners.get(type(event), []):
                runner(event, envelope.ingested_at)
            folded += 1
            if folded % 500 == 0:
                self.session.commit()
        self.session.commit()
        set_flag(self.session, DIRTY, "0")
        self._on_progress(Progress(stage="rebuild", detail=f"refolded {folded} events"
                                   + (f" ({why})" if why else "")))
        return folded

    @contextmanager
    def _unsafe(self):
        """Mark the read models 'may be half-folded' for the duration of an operation
        that appends and folds events. A crash inside leaves the mark set, so the
        next start rebuilds; so does a failure AFTER events were appended (a fold
        that raised). Nested uses share the outermost mark: no per-command commits."""
        outer = self._unsafe_depth == 0
        before = len(self.store)
        if outer:
            self._unsafe_failed = False
            set_flag(self.session, DIRTY, "1")
        self._unsafe_depth += 1
        try:
            yield
        except BaseException:
            if len(self.store) > before:         # events landed but may not have folded
                self._unsafe_failed = True
            raise
        finally:
            self._unsafe_depth -= 1
            if outer and not self._unsafe_failed:
                set_flag(self.session, DIRTY, "0")

    def _on_progress(self, payload) -> None:
        self.progress.append(payload)
        self.progress_total += 1

    def guard_root(self) -> None:
        """Raise RootVanished unless <root>/.store is still the very directory this node
        started on. A drive that was unplugged, unmounted or swapped leaves an empty
        mountpoint (or another filesystem) behind; everything written there would be a
        silent lie, so nothing may run until a person looks."""
        try:
            st = os.stat(self.root / ".store")
        except OSError as exc:
            raise RootVanished(f"{self.root} is no longer reachable ({exc.strerror or exc})") from exc
        if (st.st_dev, st.st_ino) != self._root_id:
            raise RootVanished(f"{self.root} is not the filesystem this device started on")

    def close(self) -> None:
        self.session.close()
        self.sqla.dispose()
        self.store.dag._db.close()

    def wipe(self) -> None:
        """The disk was replaced: every byte and fact of this device is gone and
        it starts a NEW life (new epoch). Its old claims survive in peers' logs
        as history; under the new epoch they no longer count."""
        self.close()
        shutil.rmtree(self.root, ignore_errors=True)
        self._create_root = True                 # a replaced disk starts empty
        self.life += 1
        self._epoch = f"{self.name}-{self.life}"
        with self._pull_lock:
            self._pull_requests.clear()
        with self._access_lock:
            self._access.clear()
        self.sweep_state.clear()
        self.progress.clear(), self.peer_health.clear(), self.transfers.clear()
        self.progress_total = 0
        self._start()

    # ── commands, queries ────────────────────────────────────────────────────

    def make_command(self, name: str, **fields) -> Any:
        cls = GRAPH.commands[name]
        if "occurred_at" in cls.model_fields and fields.get("occurred_at") is None:
            fields["occurred_at"] = datetime.now(timezone.utc)
        return cls(**fields)

    def _execute(self, command: Any) -> None:
        """Run one command. Events it emitted before failing describe real effects
        already done (a file moved to quarantine, say): record them NOW, not
        whenever the next unrelated command happens to drain the queue."""
        self.guard_root()
        try:
            self.engine.run_command(command)
        except BaseException:
            self.engine._drain_events()
            raise

    def dispatch(self, command: Any) -> None:
        """Run a command, then drain what its policies dispatched to quiescence."""
        self.guard_root()                        # before the read models are touched at all
        with self._unsafe():
            self._execute(command)
            self.drain()

    def run(self, name: str, **fields) -> None:
        if name == "announce_node":              # the live card follows what this node last declared
            self.card.update({k: v for k, v in fields.items() if k in CARD_KEYS and v is not None})
        self.dispatch(self.make_command(name, **fields))

    def note_pull_request(self, requester: str, endpoints: Optional[list[str]] = None) -> None:
        if endpoints and hasattr(self.peers, "learn"):
            self.peers.learn(requester, endpoints)     # a first-contact address hint
        with self._pull_lock:
            if requester not in self._pull_requests:   # notifications coalesce
                self._pull_requests.append(requester)

    def _next_pull_request(self) -> Optional[str]:
        with self._pull_lock:
            return self._pull_requests.pop(0) if self._pull_requests else None

    def has_work(self) -> bool:
        with self._pull_lock:
            pending = bool(self._pull_requests)
        return pending or not self.command_queue.empty()

    def drain(self) -> None:
        """Run until idle: queued commands (what policies dispatched) and peers'
        pull requests, each possibly producing more of the other."""
        if not self.has_work():
            return
        self.guard_root()
        with self._unsafe():
            while self.has_work():
                while True:
                    try:
                        queued = self.command_queue.get_nowait()
                    except Empty:
                        break
                    self._execute(queued)
                while (requester := self._next_pull_request()) is not None:
                    try:
                        self.pull_from_peer(requester)
                    except PeerUnreachable:
                        pass                           # the requester went away again

    def query(self, name: str, **fields) -> Any:
        mod = importlib.import_module(f"gen_def.pydantic.query.{name}")
        return getattr(self.queries, name)(getattr(mod, f"{camel_case(name)}Input")(**fields))

    def announce(self, **card_overrides) -> None:
        """Declare this node's public card; overrides persist in the card (this
        is how a node declares itself draining, then un-drains)."""
        self.card.update(card_overrides)
        self.run("announce_node", **{k: v for k, v in self.card.items() if k in CARD_KEYS})

    def adopt_cluster(self, cluster_id: str) -> None:
        """What the host does after create_cluster / on join: persist the id."""
        self.cluster_id = cluster_id
        self.env_store.cluster_id = cluster_id

    # ── replication ──────────────────────────────────────────────────────────

    def pull_from_surface(self, surface) -> int:
        """Anti-entropy pull + fold-on-replicate + react-on-replicate. ``surface``
        is anything with buckets()/ids()/events(): a PeerSurface or the HTTP client."""
        added = reconcile_pull(self.store, surface)
        # a merge is not a stampede: react to at most max_dispatch_per_event events of
        # each type (a bulk adoption that arrives FRESH is still a bulk — the paced
        # sweep catches the rest). Announcements and the like are few, so unaffected.
        budget: dict[str, int] = defaultdict(lambda: max(1, self.env_store.max_dispatch_per_event))

        def react(event, envelope) -> None:
            if budget[envelope.type] > 0:
                budget[envelope.type] -= 1
                self.engine.react_to_replicated(event, envelope)

        fold_envelopes(added, self.session, runners=self.runners,
                       reconstruct=self.store.reconstruct_event, after_fold=react)
        return len(added)

    def pull_from_peer(self, peer_id: str) -> int:
        return self.peers.pull_from(peer_id)

    # ── the edge: what the blob API does ────────────────────────────────────

    def edge_open(self, chunk_size: Optional[int] = None) -> StagedBlob:
        """Begin an upload. ``chunk_size`` forces a chunk recipe (scenarios);
        otherwise one is recorded only for files past env.chunk_threshold_bytes."""
        self.guard_root()
        floor = self.env_store.min_free_bytes or 0
        if floor > 0 and self.disk.free_bytes() < floor:
            raise OutOfSpace(f"only {self.disk.free_bytes()} bytes free on the disk, "
                             f"under the {floor}-byte floor — not taking uploads")
        tmp = Path(self.env_store.tmp_dir) / f"upload-{uuid.uuid4().hex}"
        return StagedBlob(tmp, chunk_size or self.env_store.chunk_size, forced=bool(chunk_size))

    def edge_commit(self, stage: StagedBlob, collection: str, lock=None) -> dict:
        """Finish an upload: place the verified bytes under root, then record them
        (put_blob). ``lock`` guards only the command, not the byte streaming."""
        digest = stage.finish()
        self.guard_root()
        dest = blob_path(self.root, digest)
        if dest.exists():
            stage.path.unlink(missing_ok=True)         # re-upload of what we already hold
        else:
            place_atomic(stage.path, dest)
        fields: dict[str, Any] = dict(blob_hash=digest, byte_size=stage.size,
                                      collection=collection)
        chunked = len(stage.chunk_hashes) > 1 and (
            stage.forced or stage.size >= self.env_store.chunk_threshold_bytes)
        if chunked:
            fields.update(chunk_size=stage.chunk_size, chunk_hashes=stage.chunk_hashes)
        with (lock if lock is not None else nullcontext()):
            self.run("put_blob", **fields)
        return {"blob_hash": digest, "byte_size": stage.size, "chunked": chunked}

    def edge_put(self, pieces: Iterable[bytes], collection: str,
                 chunk_size: Optional[int] = None, lock=None) -> str:
        stage = self.edge_open(chunk_size)
        try:
            for piece in pieces:
                stage.write(piece)
            return self.edge_commit(stage, collection, lock)["blob_hash"]
        except BaseException:
            stage.abort()
            raise

    def open_blob(self, blob_hash: str) -> Optional[Path]:
        """The edge's GET: the local file — fetched back from a peer first if it
        was evicted (replicate_blob, reason 'read_through'). None if nobody has it."""
        path = blob_path(self.root, blob_hash)
        if not path.is_file():
            self.run("replicate_blob", blob_hash=blob_hash, reason="read_through")
            if not path.is_file():
                return None
        self.note_access(blob_hash)
        return path

    def note_access(self, blob_hash: str) -> None:
        with self._access_lock:
            self._access[blob_hash] = datetime.now(timezone.utc)

    def flush_access(self) -> None:
        """Coalesce the edge's reads into one blob_access_recorded (LRU's input)."""
        with self._access_lock:
            batch, self._access = self._access, {}
        if batch:
            self.run("record_blob_access", blob_hashes=list(batch),
                     last_access_ats=list(batch.values()))

    def has_blob(self, blob_hash: str) -> bool:
        """The blob API's `has`: the bytes are there AND still match their address."""
        path = blob_path(self.root, blob_hash)
        try:
            return path.is_file() and sha256_file(path) == blob_hash
        except OSError:                                  # a file nobody can read is not a copy
            return False
