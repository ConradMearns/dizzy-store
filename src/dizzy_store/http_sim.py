"""A cluster whose devices talk over REAL HTTP on localhost.

``HttpCluster`` is a SimCluster in which every device serves the real peer API
(``peer_http.make_peer_router``) on its own socket and reaches the others
through the real client (``HttpPeers``) — so the same scenarios that specify the
behavior in simulation can be run against the actual transport (see
tests/test_scenarios_http.py). Only two things stay simulated: the clock, and
"offline / partitioned", which is a gate in each device's peer router (a real
network fault would just be a refused connection; the client treats a 503 from
the gate exactly like one).
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from .node import StoreNode
from .peer_http import HttpPeers, make_peer_router
from .sim import SimCluster

TOKEN = "conformance-token"


def reserve_port() -> socket.socket:
    """Bind an ephemeral loopback port now, so a device can put its URL on its
    card before its server starts (no bind race: the socket is handed to uvicorn)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    return sock


class ThreadedServer:
    """An ASGI app served by uvicorn on a thread, on a reserved socket."""

    def __init__(self, app: FastAPI, sock: socket.socket):
        self.sock = sock
        self.port = sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        self.thread = threading.Thread(
            target=lambda: self.server.run(sockets=[self.sock]), daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "ThreadedServer":
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.005)
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.sock.close()


class _Ping(BaseModel):          # module level: FastAPI resolves annotations by module globals
    x: int = 0


def _warm_imports() -> None:
    """Import, while the clock is real, everything FastAPI/uvicorn import lazily.

    Scenarios run under a frozen clock (freezegun), which replaces datetime.date;
    pydantic.v1 — imported by FastAPI the first time it builds a route — defines a
    class deriving from it, and fails with a metaclass conflict if that import
    happens while frozen. Serving one request now loads all of it up front."""
    import httpx
    import pydantic.v1  # noqa: F401

    app = FastAPI()

    @app.post("/ping")
    def ping(body: _Ping):
        return {"x": body.x}

    server = ThreadedServer(app, reserve_port()).start()
    try:
        httpx.post(f"{server.url}/ping", json={"x": 1}, timeout=5).raise_for_status()
    finally:
        server.stop()


_warm_imports()


class HttpCluster(SimCluster):
    def __init__(self, home: str | Path, cluster_id: str = "cluster-1"):
        super().__init__(home, cluster_id)
        self.seeds: dict[str, str] = {}              # shared with every client
        self._servers: dict[str, ThreadedServer] = {}

    def _new_node(self, name: str, cluster_id: Optional[str], card, config) -> StoreNode:
        # the node must exist before its server (the router closes over it), and its
        # card must carry the URL — so build, bind, then announce the endpoint.
        sock = reserve_port()
        node = StoreNode(name, self.home / name, cluster_id=cluster_id,
                         card={**(card or {})}, config=config, epoch=f"{name}-1")
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        node.card["endpoints"] = [url]
        node.peers = HttpPeers(node, TOKEN, seeds=self.seeds)
        app = FastAPI()
        app.include_router(make_peer_router(
            node, TOKEN, lambda requester, n=name: self.reachable(requester, n)))
        self.seeds[name] = url
        self._servers[name] = ThreadedServer(app, sock).start()
        return node

    def close(self) -> None:
        for server in self._servers.values():
            server.stop()
        for node in self.nodes.values():
            node.close()
