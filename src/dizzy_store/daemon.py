"""The device daemon: the peer API for other devices, an admin API for the local
operator, and the tick loop that keeps the device doing its job.

One process owns the device. Peer requests (other devices pulling events, reading
blobs) touch only the event store and files, never the read-model session, so they
are served concurrently with the loop. Everything that runs commands — the loop and
the admin API — takes ``Daemon.lock``, which serializes the single-threaded engine.
"""
from __future__ import annotations

import contextlib
import logging
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from .config import ConfigError, Resolved
from .device import Device
from .exitcodes import EX_CONFIG, EX_IOERR, EX_TEMPFAIL
from .node import DEFAULT_CONFIG, StoreNode
from .peer_http import HttpPeers, RemoteSurface, make_peer_router
from .sdnotify import notify
from .sweep import sweep
from gen_def.pydantic.environment import Store
from storeutil import OutOfSpace, PeerUnreachable, RootVanished, is_hash

log = logging.getLogger("dizzy_store")


@dataclass
class IdlePolicy:
    """When has a device nothing left to do? `run --until-idle`: it holds exactly the events of at least one
    peer, wants no blob it lacks, and nothing has changed for ``settle_s``."""
    settle_s: float = 4.0            # nothing may change for this long
    grace_s: float = 30.0            # how long to wait to reach ANY peer before giving up
    stall_s: float = 30.0            # reached a peer, but still not in step after this long with no change
    max_s: Optional[float] = None    # an overall ceiling (None: as long as it is making progress)
    report_s: float = 10.0           # a progress line this often



class Daemon:
    def __init__(self, device: Device, node: Optional[StoreNode] = None,
                 gate: Optional[Callable[[str], bool]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 reresolve: Optional[Callable[[], Resolved]] = None):
        self.device = device
        self.reresolve = reresolve               # how to re-read the configuration (SIGHUP); None = cannot
        self.node = node or device.build_node()
        self.node.peers = HttpPeers(self.node, device["peer_token"], seeds=device["seeds"])
        self.lock = threading.RLock()            # serializes the engine
        self.stop = threading.Event()
        self._clock = clock
        self._last: dict[str, float] = {}
        self._progress_seen = 0
        self.exit_code = 0
        self.server: Optional[uvicorn.Server] = None
        self._reload = threading.Event()
        self.listening = threading.Event()       # set by serve() once the listener is up
        self.loop_done = False                   # serve() returned with the tick thread really stopped
        self.passes = 0                          # full ticks completed
        self.reached: set[str] = set()           # peers that answer right now (until-idle's view)
        self.in_step: set[str] = set()           # ... and of those, the ones holding exactly our events
        self.fast: Optional[float] = None        # until-idle: sync, sweep and capacity run every tick
        self.idle_result: Optional[tuple[int, str]] = None
        self.app = build_app(self, gate)

    # ── reload ───────────────────────────────────────────────────────────────

    def request_reload(self) -> None:
        """SIGHUP's handler: just a flag — the loop thread does the work, under the lock."""
        self._reload.set()

    def reload(self) -> list[str]:
        """Re-read the configuration and apply what can change live: limits, the free-space floor,
        pacing, cadence, seeds, and the announced card. A bad file is REFUSED and the running
        configuration kept (a typo must not take a backup off the air); a changed `listen` or
        `root` needs a restart and says so. Returns what changed."""
        if self.reresolve is None:
            log.warning("reload requested, but this daemon was not started with a way to re-read its configuration")
            return []
        try:
            resolved = self.reresolve()
        except ConfigError as exc:
            log.error("reload refused — keeping the running configuration: %s", exc)
            return []
        changed: list[str] = []
        with self.lock:
            old, device = self.device.settings, self.device
            was = {k: device[k] for k in ("listen", "endpoints", "seeds", "intervals", "config")}
            device.settings = resolved.settings
            now = {k: device[k] for k in was}
            if resolved.root.resolve() != device.root.resolve():
                log.warning("the configured root changed — restart to use it (still running on %s)", device.root)
            if now["listen"] != was["listen"]:
                log.warning("`listen` changed to %s — restart to use it (still listening on %s)",
                            now["listen"], was["listen"])
                device.settings = device.settings.model_copy(update={"listen": old.listen})
            env = {**DEFAULT_CONFIG, **now["config"]}
            for key, value in env.items():          # env.store is validated on assignment
                if key in Store.model_fields and getattr(self.node.env_store, key, None) != value:
                    setattr(self.node.env_store, key, value)
                    changed.append(f"{key}={value}")
            self.node.config.update(env)
            if now["seeds"] != was["seeds"]:
                self.node.peers.set_seeds(now["seeds"])
                changed.append("seeds")
            if now["intervals"] != was["intervals"]:
                changed.append("intervals")
            card = device.card
            if card != {k: self.node.card.get(k) for k in card}:
                self.node.card.update(card)
                self.node.announce()
                changed.append("announced card")
        logging.getLogger().setLevel(resolved.loaded.config.log_level.upper())
        log.info("reloaded the configuration: %s", ", ".join(changed) or "nothing changed")
        return changed

    def fatal(self, exc: Exception) -> None:
        """The store's root is gone (a drive was unplugged or unmounted): stop everything
        and exit non-zero. Never recoverable from inside — `systemctl --user start` after
        the drive is back is a person's decision."""
        if self.exit_code:
            return                                     # already stopping
        log.error("%s — stopping the daemon; nothing more will be written", exc)
        self.exit_code = EX_IOERR
        self.stop.set()
        if self.server is not None:
            self.server.should_exit = True

    # ── peers ────────────────────────────────────────────────────────────────

    def peer_ids(self) -> list[str]:
        with self.lock:
            known = self.node.query("list_peers", node_id=self.node.name).node_ids
        ids = list(dict.fromkeys([*known, *self.device["seeds"]]))
        return [p for p in ids if p != self.node.name]

    # ── the tick ─────────────────────────────────────────────────────────────

    def announce(self) -> None:
        if not self.node.cluster_id:
            log.warning("no cluster yet — `found` or `join` before running; not announcing")
            return
        with self.lock:
            self.node.announce()
            log.info("announced %s as %s at site %s (epoch %s)", self.node.name,
                     self.node.card["role"], self.node.card["site"], self.node.epoch)

    def _due(self, name: str, force: bool) -> bool:
        if self.fast is not None and name in ("sync", "sweep", "capacity"):
            interval = self.fast
        else:
            interval = self.device["intervals"].get(f"{name}_s", 60)
        now = self._clock()
        if force or now - self._last.get(name, float("-inf")) >= interval:
            self._last[name] = now
            return True
        return False

    def _guarded(self, label: str, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except PeerUnreachable as exc:
            log.info("%s: %s", label, exc)
        except RootVanished as exc:
            self.fatal(exc)
        except Exception:
            log.exception("%s failed", label)

    def tick(self, force: bool = False) -> None:
        """One pass of the device's periodic work. ``force`` runs everything now."""
        if not self.node.cluster_id:
            return
        node = self.node
        try:
            node.guard_root()                          # the drive is still there, and still THAT drive
        except RootVanished as exc:
            self.fatal(exc)
            return
        if self._due("sync", force):
            for peer in self.peer_ids():
                with self.lock:
                    self._guarded(f"sync {peer}", lambda p=peer: node.run(
                        "sync_peer", peer_id=p, direction="both"))
        with self.lock:
            self._guarded("drain", node.drain)
            if self._due("sweep", force):
                self._guarded("sweep", lambda: log.info("sweep: %s", sweep(node)))
            if self._due("capacity", force):
                self._guarded("capacity", lambda: node.run("check_capacity"))
            if self._due("access", force):
                self._guarded("access", node.flush_access)
            if self._due("scrub", force):
                self._guarded("scrub", lambda: node.run(
                    "scrub_blobs", max_bytes=self.device["intervals"].get(
                        "scrub_budget_bytes", 1 << 30)))
            self._log_progress()
        self.passes += 1

    # ── "until idle": plug in, sync, unplug ──────────────────────────────────

    def activity(self) -> tuple[int, int, int, int]:
        """(events in the log, blobs held, blobs still wanted, of those how many are backing off after a
        failed fetch) — the numbers that change while there is work being done."""
        with self.lock:
            node = self.node
            held = node.query("get_node_usage", node_id=node.name).held_count
            wanted = node.query("get_missing_blobs", node_id=node.name).blob_hashes or []
            now = datetime.now(timezone.utc)
            backing_off = 0
            for blob_hash in wanted:
                _fails, retry_after = node.sweep_state.get(("replicate", blob_hash), (0, None))
                backing_off += retry_after is not None and now < retry_after
            return len(node.store), held, len(wanted), backing_off

    def compare_with_peers(self) -> None:
        """Which peers answer right now, and which of those hold exactly the events this device holds?
        Their digest of the log against ours: equal means each has everything the other has — that proves the
        PUSH as well as the pull, which a peer merely accepting our pull request does not."""
        for peer in self.peer_ids():
            with self.lock:         # the peers client looks the peer's address up in the node's read models, and a
                try:                # SQLAlchemy session is not thread-safe: never beside the tick, as sync_peer is not
                    theirs = RemoteSurface(self.node.peers, peer).buckets()
                except PeerUnreachable:
                    self.reached.discard(peer)
                    self.in_step.discard(peer)
                    continue
                self.reached.add(peer)
                ours = self.node.surface.buckets()
            (self.in_step.add if theirs == ours else self.in_step.discard)(peer)

    def summary(self) -> str:
        with self.lock:
            usage = self.node.query("get_node_usage", node_id=self.node.name)
            events = len(self.node.store)
        ids = self.peer_ids()
        peers = [("in step with", sorted(self.in_step)),
                 ("answering but not in step", sorted(self.reached - self.in_step)),
                 ("not answering", sorted(set(ids) - self.reached))]
        said = "; ".join(f"{label} {', '.join(names)}" for label, names in peers if names) or "no peers known"
        return (f"{self.node.name}: {usage.held_count:,} blobs held ({usage.held_bytes / 2**30:.2f} GiB), "
                f"{events:,} events; {said}")

    def _log_progress(self) -> None:
        total = self.node.progress_total
        fresh = total - self._progress_seen
        if fresh > 0:
            kept = list(self.node.progress)
            for p in kept[-min(fresh, len(kept)):]:
                log.info("%s: %s", p.stage, p.detail)
        self._progress_seen = total

    def catch_up(self) -> None:
        """Pull every known peer's log WITHOUT announcing or pushing yet. A device
        that is back from a wipe has an empty log; its announcement must be stamped
        strictly after its previous life's, and it can only know that by reading it."""
        if not self.node.cluster_id:
            return
        for peer in self.peer_ids():
            with self.lock:
                self._guarded(f"catch up from {peer}", lambda p=peer: self.node.run(
                    "sync_peer", peer_id=p, direction="pull"))

    def loop(self) -> None:
        if self.server is not None:              # under serve(): act on the store only once we are LISTENING —
            while not self.listening.wait(0.1):  # a process that cannot bind its port (it is already running
                if self.stop.is_set():           # elsewhere) must not have announced anything
                    return
        self.catch_up()
        self.announce()
        while not self.stop.is_set():
            if self._reload.is_set():
                self._reload.clear()
                self.reload()
            self.tick()
            self.stop.wait(1.0)

    # ── status ───────────────────────────────────────────────────────────────

    def status(self, risk: bool = False) -> dict:
        """What this device holds and knows. ``risk`` adds the at-risk scan, which
        walks every blob's placement — opt-in, so a status poll stays cheap."""
        node = self.node
        with self.lock:
            peers = node.query("list_peers", node_id=node.name)
            usage = node.query("get_node_usage", node_id=node.name)
            at_risk = node.query("get_at_risk_blobs", limit=20) if risk else None
            return {
                "node_id": node.name, "epoch": node.epoch, "cluster_id": node.cluster_id,
                "role": node.card["role"], "site": node.card["site"],
                "held_count": usage.held_count, "held_bytes": usage.held_bytes,
                "limit_bytes": node.env_store.limit_bytes,
                "events": len(node.store),
                "peers": [{"node_id": n, "role": r, "site": s, "draining": d}
                          for n, r, s, d in zip(peers.node_ids, peers.roles,
                                                peers.sites, peers.drainings)],
                "at_risk": None if at_risk is None else [
                    {"blob_hash": h, "sites_holding": a, "sites_needed": b}
                    for h, a, b in zip(at_risk.blob_hashes, at_risk.sites_holding,
                                       at_risk.sites_needed)],
                "recent": [f"{p.stage}: {p.detail}" for p in list(node.progress)[-10:]],
            }


# ── the HTTP app ─────────────────────────────────────────────────────────────

def build_app(daemon: Daemon, gate: Optional[Callable[[str], bool]] = None) -> FastAPI:
    app = FastAPI(title=f"dizzy-store {daemon.node.name}", docs_url=None, redoc_url=None)
    app.include_router(make_peer_router(daemon.node, daemon.device["peer_token"], gate))
    admin = APIRouter(prefix="/admin")

    def admin_guard(request: Request) -> None:
        import hmac
        auth = request.headers.get("authorization", "")
        if not (auth.startswith("Bearer ")
                and hmac.compare_digest(auth[7:], daemon.device["admin_token"])):
            raise HTTPException(401, "bad or missing admin token")

    deps = [Depends(admin_guard)]

    def failed(exc: Exception) -> JSONResponse:
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=400)

    @admin.get("/status", dependencies=deps)
    def status(risk: bool = False):
        return daemon.status(risk)

    @admin.post("/command", dependencies=deps)
    def command(body: dict):
        try:
            with daemon.lock:
                daemon.node.run(body["name"], **(body.get("fields") or {}))
            return {"ok": True}
        except Exception as exc:
            return failed(exc)

    @admin.post("/query", dependencies=deps)
    def query(body: dict):
        try:
            with daemon.lock:
                return daemon.node.query(body["name"], **(body.get("input") or {})).model_dump(mode="json")
        except Exception as exc:
            return failed(exc)

    @admin.post("/sweep", dependencies=deps)
    def do_sweep():
        with daemon.lock:
            return sweep(daemon.node)

    @admin.post("/tick", dependencies=deps)
    def do_tick():
        daemon.tick(force=True)
        return {"ok": True}

    @admin.post("/sync/{peer}", dependencies=deps)
    def do_sync(peer: str):
        try:
            with daemon.lock:
                daemon.node.run("sync_peer", peer_id=peer, direction="both")
            return {"ok": True}
        except Exception as exc:
            return failed(exc)

    @admin.put("/blob", dependencies=deps)
    async def upload(request: Request, collection: str = "default"):
        """The edge's PUT: stream the body into a temp file, hash it, place it
        under root, then record it (put_blob). The hash is the receipt."""
        try:
            stage = daemon.node.edge_open()
        except OutOfSpace as exc:
            return JSONResponse({"error": str(exc)}, status_code=507)     # Insufficient Storage
        except RootVanished as exc:
            daemon.fatal(exc)
            return JSONResponse({"error": str(exc)}, status_code=503)
        try:
            async for piece in request.stream():
                await run_in_threadpool(stage.write, piece)
            result = await run_in_threadpool(
                daemon.node.edge_commit, stage, collection, daemon.lock)
        except RootVanished as exc:
            daemon.fatal(exc)
            stage.abort()
            return JSONResponse({"error": str(exc)}, status_code=503)
        except Exception as exc:
            stage.abort()
            return failed(exc)
        return result

    @admin.get("/blob/{blob_hash}", dependencies=deps)
    def download(blob_hash: str):
        """The edge's GET, with read-through: a blob evicted here is fetched back
        from a peer (replicate_blob, reason 'read_through') before it is served."""
        if not is_hash(blob_hash):
            raise HTTPException(400, "not a sha256")
        with daemon.lock:
            path = daemon.node.open_blob(blob_hash)
        if path is None:
            raise HTTPException(404, "not held here and no peer could supply it")
        size = path.stat().st_size

        def pieces():
            with open(path, "rb") as f:
                while piece := f.read(1 << 16):
                    yield piece

        return StreamingResponse(pieces(), media_type="application/octet-stream",
                                 headers={"Content-Length": str(size)})

    app.include_router(admin)
    return app


# ── running it ───────────────────────────────────────────────────────────────

class _Server(uvicorn.Server):
    """uvicorn catches SIGTERM/SIGINT, shuts down — and then RE-RAISES the signal, which kills the
    process before serve() can stop the tick thread or say STOPPING=1 (and gives a parent an exit
    status of -15, not 0). serve() catches the signals itself, so a stop is an ordinary return."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


def _watch_idle(daemon: Daemon, server: uvicorn.Server, policy: IdlePolicy,
                say: Callable[[str], None]) -> None:
    """Stop the server when the device has nothing left to do (see IdlePolicy), recording why in
    ``daemon.idle_result`` — (0, "up to date") or (EX_TEMPFAIL, what is missing)."""
    started = time.monotonic()
    last: Optional[tuple] = None
    quiet_since = last_report = last_look = started

    def done(code: int, message: str) -> None:
        daemon.idle_result = (code, message)
        daemon.stop.set()
        server.should_exit = True

    while not server.should_exit and not daemon.stop.is_set():
        time.sleep(0.25)
        now = time.monotonic()
        if policy.max_s is not None and now - started > policy.max_s:
            return done(EX_TEMPFAIL, f"gave up after {policy.max_s:.0f}s — {daemon.summary()}")
        if not daemon.listening.is_set() or daemon.passes < 1 or now - last_look < 1.0:
            continue                                     # nothing to judge yet; and look once a second
        last_look = now
        try:
            daemon.compare_with_peers()
            snapshot = (*daemon.activity(), tuple(sorted(daemon.in_step)))
        except Exception:                                # a surprise must not leave a person waiting forever
            log.exception("until-idle: could not look at the device")
            continue
        if not daemon.reached:
            if now - started > policy.grace_s:
                return done(EX_TEMPFAIL, "reached no peer — is the drive's cluster reachable from here? (peers: "
                            + (", ".join(daemon.peer_ids()) or "none known; `join` one first") + ")")
            continue
        if snapshot != last:
            last, quiet_since = snapshot, now
        _events, held, wanted, backing_off, in_step = snapshot
        if now - last_report >= policy.report_s:
            last_report = now
            say(f"  {held:,} blobs held, {wanted:,} still wanted…")
        quiet = now - quiet_since
        if quiet >= policy.settle_s and in_step:
            if wanted == 0:
                return done(0, f"up to date — {daemon.summary()}")
            if backing_off == wanted:
                return done(EX_TEMPFAIL, f"{wanted:,} wanted blobs could not be fetched — the log says why "
                            f"(a peer asleep, none holding them, or the free-space floor) — {daemon.summary()}")
        if quiet >= policy.stall_s and not in_step:
            return done(EX_TEMPFAIL, "reached a peer but cannot get in step with it — it must be able to reach "
                        "back to pull this drive's events (check `listen` / `endpoints` and the route from "
                        f"that peer to here) — {daemon.summary()}")


def serve(daemon: Daemon, sockets=None, idle: Optional[IdlePolicy] = None,
          say: Callable[[str], None] = lambda _: None, stop_wait: float = 60.0) -> int:
    """Run the HTTP server (blocking) with the tick loop beside it. Returns the process's exit status: 0
    for an ordinary stop, EX_IOERR if the store's root vanished, EX_CONFIG if it cannot listen. With
    ``idle`` the device runs only until it has nothing left to do (0), or cannot finish (EX_TEMPFAIL). A tick
    in flight when the server stops gets ``stop_wait`` seconds to reach a stopping point."""
    host, port = daemon.device.host_port
    config = uvicorn.Config(daemon.app, host=host, port=port, log_level="warning")
    server = _Server(config)
    daemon.server = server
    if idle is not None:
        daemon.fast = 1.0                                # a pass a second, not every 30-60s: someone is waiting
    loop = threading.Thread(target=daemon.loop, name="store-loop", daemon=True)
    loop.start()
    threading.Thread(target=_announce_ready, args=(daemon, server), name="store-ready", daemon=True).start()
    if idle is not None:
        threading.Thread(target=_watch_idle, args=(daemon, server, idle, say),
                         name="store-idle", daemon=True).start()

    def stop_on(signum, _frame):
        if server.should_exit and signum == signal.SIGINT:
            server.force_exit = True                                 # a second Ctrl-C means it
        log.info("received %s — stopping", signal.Signals(signum).name)
        daemon.stop.set()
        server.should_exit = True

    saved: dict[int, Any] = {}
    if threading.current_thread() is threading.main_thread():       # signals can only be caught here
        saved[signal.SIGHUP] = signal.signal(signal.SIGHUP, lambda *_: daemon.request_reload())
        for sig in (signal.SIGTERM, signal.SIGINT):
            saved[sig] = signal.signal(sig, stop_on)
    try:
        server.run(sockets=sockets)
    except SystemExit:
        if server.started:
            raise                       # a real stop that somebody asked for
        # uvicorn gave up before it ever listened: the address is taken. A restart cannot fix that.
        log.error("cannot listen on %s:%s — another program (or another dizzy-store) is using it; "
                  "give this device a free `listen:` in the configuration", host, port)
        daemon.exit_code = EX_CONFIG
    finally:
        notify("STOPPING=1")
        for sig, handler in saved.items():
            signal.signal(sig, handler)
        daemon.stop.set()
        loop.join(timeout=stop_wait)    # let a transfer in flight reach a stopping point (its chunks are kept)
        daemon.loop_done = not loop.is_alive()
        if not daemon.loop_done:
            log.warning("the tick loop is still busy after %gs — leaving the store open", stop_wait)
    if daemon.idle_result is not None and not daemon.exit_code:
        return daemon.idle_result[0]
    return daemon.exit_code


def _announce_ready(daemon: Daemon, server: uvicorn.Server, timeout: float = 60.0) -> None:
    """Tell systemd (Type=notify) the daemon is up — once its listener really is."""
    deadline = time.monotonic() + timeout
    while not server.started and not daemon.stop.is_set() and time.monotonic() < deadline:
        time.sleep(0.02)
    if server.started:
        daemon.listening.set()
        host, port = daemon.device.host_port
        notify(f"READY=1\nSTATUS={daemon.node.name} serving on {host}:{port}")
