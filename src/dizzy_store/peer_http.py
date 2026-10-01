"""The peer API over HTTP — what one device offers another — and its client.

Both directions are thin: the router just exposes ``node.surface`` (the same
PeerSurface the simulation calls in-process) and ``HttpPeers`` is the real
counterpart of ``SimPeers``. A device is "unreachable" exactly when a request to
it fails to connect or time out; reachability is observation, never a fact.

Security (v0): a shared bearer token on every /peer request, with the listener
bound to loopback and reached through a private tunnel (SSH today, a tailnet
later — the card's endpoints are plain URLs, so the transport is swappable).
"""
from __future__ import annotations

import hmac
import re
from typing import Callable, Iterator, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dagstore import Event
from storeutil import PeerUnreachable, is_hash


# ── wire format ──────────────────────────────────────────────────────────────

def event_to_json(event: Event) -> dict:
    return {"id": event.id, "type": event.type, "parents": list(event.parents),
            "payload": event.payload}


def event_from_json(d: dict) -> Event:
    return Event(id=d["id"], type=d["type"], parents=tuple(d["parents"]), payload=d["payload"])


class _Prefixes(BaseModel):
    prefixes: list[str]


class _Ids(BaseModel):
    ids: list[str]


class _PullRequest(BaseModel):
    requester: str
    endpoints: list[str] = []      # where the requester can be reached — a first-contact hint


def parse_range(header: str, size: int) -> Optional[tuple[int, int]]:
    """A single ``bytes=a-b`` / ``bytes=a-`` / ``bytes=-n`` range -> inclusive
    (start, end), or None for no/unsupported range. Raises ValueError when the
    range cannot be satisfied (HTTP 416)."""
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    first, last = m.groups()
    if first == "":
        start, end = max(0, size - int(last)), size - 1
    else:
        start, end = int(first), (int(last) if last else size - 1)
    end = min(end, size - 1)
    if size == 0 or start > end:
        raise ValueError("unsatisfiable")
    return start, end


# ── the server side ──────────────────────────────────────────────────────────

def make_peer_router(node, token: str,
                     gate: Optional[Callable[[str], bool]] = None) -> APIRouter:
    """The /peer router for one device.

    ``gate(requester_id) -> bool`` is a test seam: simulating "this device is
    unreachable from that one" (offline / partition) in a conformance cluster. It
    is None in production."""
    router = APIRouter(prefix="/peer")

    def guard(request: Request) -> None:
        auth = request.headers.get("authorization", "")
        if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], token)):
            raise HTTPException(401, "bad or missing peer token")
        if gate is not None and not gate(request.headers.get("x-peer-id", "")):
            raise HTTPException(503, "unreachable")

    deps = [Depends(guard)]

    @router.get("/cluster", dependencies=deps)
    def cluster():
        return {"cluster_id": node.surface.cluster_id(), "node_id": node.name,
                "epoch": node.epoch}

    @router.get("/buckets", dependencies=deps)
    def buckets():
        return {"buckets": node.surface.buckets()}

    @router.post("/ids", dependencies=deps)
    def ids(body: _Prefixes):
        return {"ids": node.surface.ids(body.prefixes)}

    @router.post("/events", dependencies=deps)
    def events(body: _Ids):
        return {"events": [event_to_json(e) for e in node.surface.events(body.ids)]}

    @router.get("/blob/{blob_hash}/stat", dependencies=deps)
    def stat(blob_hash: str):
        size = node.surface.blob_size(blob_hash) if is_hash(blob_hash) else None
        if size is None:
            raise HTTPException(404, "not held")
        return {"size": size}

    @router.get("/blob/{blob_hash}/verify", dependencies=deps)
    def verify(blob_hash: str):
        if not is_hash(blob_hash):
            raise HTTPException(400, "not a sha256")
        return node.surface.verify_blob(blob_hash)

    @router.get("/blob/{blob_hash}", dependencies=deps)
    def blob(blob_hash: str, request: Request):
        size = node.surface.blob_size(blob_hash) if is_hash(blob_hash) else None
        if size is None:
            raise HTTPException(404, "not held")
        try:
            rng = parse_range(request.headers.get("range", ""), size)
        except ValueError:
            raise HTTPException(416, "range not satisfiable",
                                headers={"Content-Range": f"bytes */{size}"})
        start, end = rng if rng else (0, size - 1)
        length = end - start + 1
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(length)}
        if rng:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(
            node.surface.read_blob(blob_hash, start, length),
            status_code=206 if rng else 200, headers=headers,
            media_type="application/octet-stream")

    @router.post("/pull-request", status_code=202, dependencies=deps)
    def pull_request(body: _PullRequest):
        node.surface.request_pull(body.requester, body.endpoints)
        return {"accepted": True}

    return router


# ── the client side ──────────────────────────────────────────────────────────

class RemoteSurface:
    """One peer, as the anti-entropy sees it (buckets / ids / events)."""

    def __init__(self, peers: "HttpPeers", peer_id: str):
        self._peers, self._peer_id = peers, peer_id

    def buckets(self) -> dict:
        return self._peers.request_json(self._peer_id, "GET", "/peer/buckets")["buckets"]

    def ids(self, prefixes) -> list[str]:
        return self._peers.request_json(
            self._peer_id, "POST", "/peer/ids", json={"prefixes": list(prefixes)})["ids"]

    def events(self, ids) -> list[Event]:
        data = self._peers.request_json(
            self._peer_id, "POST", "/peer/events", json={"ids": list(ids)})
        return [event_from_json(d) for d in data["events"]]


class HttpPeers:
    """The real peers client — the counterpart of SimPeers.

    A peer's address is its ANNOUNCED endpoints (from the replicated log),
    bootstrapped by ``seeds`` (name -> url, shared by reference so a cluster can
    add to it) and by the endpoint HINT a peer sends when it asks to be pulled
    (``learn``) — without that, a device could never answer the first "pull from
    me" from a peer it has not yet read the announcement of. Any transport
    failure (refused, timeout, a 502/503/504 from a tunnel or proxy) is
    PeerUnreachable; anything else — a wrong token, a 5xx from the app itself —
    is a real error and raises."""

    def __init__(self, node, token: str, seeds: Optional[dict] = None,
                 client: Optional[httpx.Client] = None,
                 connect_timeout: float = 5.0, read_timeout: float = 60.0,
                 verify_timeout: float = 900.0):
        self._node = node
        self._verify_timeout = verify_timeout
        self._seeds = seeds if seeds is not None else {}
        self._hints: dict[str, list[str]] = {}
        self._headers = {"Authorization": f"Bearer {token}", "X-Peer-Id": node.name}
        self._http = client or httpx.Client(
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout))
        self._last_good: dict[str, str] = {}

    def set_seeds(self, seeds: dict) -> None:
        """Replace the bootstrap addresses in place (a config reload changed them)."""
        self._seeds.clear()
        self._seeds.update(seeds)

    # addresses ---------------------------------------------------------------

    def _bases(self, peer_id: str) -> list[str]:
        bases: list[str] = []
        if peer_id in self._last_good:
            bases.append(self._last_good[peer_id])
        profile = self._node.query("get_node_profile", node_id=peer_id)
        if profile.found:
            bases += list(profile.endpoints or [])
        bases += self._hints.get(peer_id, [])
        if peer_id in self._seeds:
            bases.append(self._seeds[peer_id])
        seen: set[str] = set()
        ordered = [b.rstrip("/") for b in bases if not (b in seen or seen.add(b))]
        if not ordered:
            raise PeerUnreachable(f"no known address for {peer_id}")
        return ordered

    # requests ----------------------------------------------------------------

    def _send(self, peer_id: str, method: str, path: str, *, stream: bool = False,
              headers: Optional[dict] = None, **kwargs) -> httpx.Response:
        errors: list[str] = []
        for base in self._bases(peer_id):
            try:
                request = self._http.build_request(
                    method, base + path, headers={**self._headers, **(headers or {})}, **kwargs)
                response = self._http.send(request, stream=stream)
            except (httpx.TransportError, httpx.InvalidURL) as exc:
                errors.append(f"{base}: {type(exc).__name__}")
                continue
            if response.status_code in (502, 503, 504):
                response.close()
                errors.append(f"{base}: HTTP {response.status_code}")
                continue
            self._last_good[peer_id] = base
            return response
        raise PeerUnreachable(f"{peer_id} unreachable ({'; '.join(errors)})")

    def request_json(self, peer_id: str, method: str, path: str, **kwargs) -> dict:
        response = self._send(peer_id, method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    # the peers-client contract (what the procedures call) -------------------

    def learn(self, peer_id: str, endpoints: list[str]) -> None:
        """Remember where a peer says it can be reached (never overrides announcements)."""
        self._hints[peer_id] = list(endpoints)

    def cluster_id(self, peer_id: str) -> Optional[str]:
        return self.request_json(peer_id, "GET", "/peer/cluster").get("cluster_id")

    def pull_from(self, peer_id: str) -> int:
        return self._node.pull_from_surface(RemoteSurface(self, peer_id))

    def request_pull(self, peer_id: str) -> None:
        self.request_json(peer_id, "POST", "/peer/pull-request",
                          json={"requester": self._node.name,
                                "endpoints": list(self._node.card.get("endpoints") or [])})

    def blob_size(self, peer_id: str, blob_hash: str) -> Optional[int]:
        response = self._send(peer_id, "GET", f"/peer/blob/{blob_hash}/stat")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["size"]

    def verify_blob(self, peer_id: str, blob_hash: str) -> dict:
        """Ask a peer to PROVE it holds the bytes (it re-hashes the file) and to report
        its live role and draining state. Re-hashing a large file takes a while, so this
        call waits far longer than an ordinary request."""
        response = self._send(peer_id, "GET", f"/peer/blob/{blob_hash}/verify",
                              timeout=httpx.Timeout(self._verify_timeout, connect=5.0))
        response.raise_for_status()
        return response.json()

    def read_blob(self, peer_id: str, blob_hash: str, offset: int = 0,
                  length: Optional[int] = None) -> Iterator[bytes]:
        headers = {}
        if offset or length is not None:
            end = "" if length is None else str(offset + length - 1)
            headers["Range"] = f"bytes={offset}-{end}"
        response = self._send(peer_id, "GET", f"/peer/blob/{blob_hash}",
                              stream=True, headers=headers)
        try:
            if response.status_code == 404:
                raise PeerUnreachable(f"{peer_id} does not hold {blob_hash[:12]}")
            response.raise_for_status()
            for piece in response.iter_bytes(1 << 16):
                yield piece
        except httpx.TransportError as exc:          # dropped mid-stream
            raise PeerUnreachable(f"{peer_id} dropped the transfer: {type(exc).__name__}")
        finally:
            response.close()
