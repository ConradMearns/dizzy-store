"""Two REAL devices — real daemons, real sockets, the real CLI — end to end.

The scenario suites prove behavior (in simulation and over HTTP); this proves the
shipped pieces work together the way an operator uses them: init, found, join,
announce, put a file, watch it replicate, evict it from the hot device, read it
back through the evicted device, survive a restart.
"""
import hashlib
import os
from pathlib import Path

import httpx
import pytest

from dizzy_store.cli import main as cli
from dizzy_store.daemon import Daemon
from dizzy_store.device import Device
from dizzy_store.http_sim import ThreadedServer, reserve_port
from storeutil import blob_path

TOKEN = "shared-secret"


class Running:
    """A device's daemon on an ephemeral port. The tick loop is NOT started —
    tests drive ticks themselves, so every step is deterministic."""

    def __init__(self, root: Path):
        self.root = root
        sock = reserve_port()
        device = Device.load(root)
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        device.data["listen"] = url.removeprefix("http://")
        device.data["endpoints"] = [url]
        device.save()
        self.daemon = Daemon(device)
        self.server = ThreadedServer(self.daemon.app, sock).start()
        self.admin = httpx.Client(base_url=url, timeout=30,
                                  headers={"Authorization": f"Bearer {device['admin_token']}"})

    @property
    def url(self) -> str:
        return self.server.url

    def command(self, name, **fields):
        r = self.admin.post("/admin/command", json={"name": name, "fields": fields})
        assert r.status_code == 200, r.text
        return r.json()

    def stop(self):
        if getattr(self, "_stopped", False):
            return                                   # idempotent: fixtures stop what tests already stopped
        self._stopped = True
        self.server.stop()
        self.daemon.node.close()


@pytest.fixture
def pair(tmp_path):
    srv_root, lap_root = tmp_path / "server", tmp_path / "laptop"
    assert cli(["--root", str(srv_root), "init", "--node-id", "server", "--role", "hot",
                "--site", "hetzner", "--limit-bytes", "100KB", "--peer-token", TOKEN]) == 0
    assert cli(["--root", str(lap_root), "init", "--node-id", "laptop", "--role", "archive",
                "--site", "home", "--wants", "*", "--limit-bytes", "10MB",
                "--peer-token", TOKEN]) == 0
    assert cli(["--root", str(srv_root), "found"]) == 0
    server = Running(srv_root)
    assert cli(["--root", str(lap_root), "join", "--url", server.url]) == 0
    laptop = Running(lap_root)
    server.daemon.announce()
    laptop.daemon.announce()
    # introductions: the laptop pulls the server's log and asks the server to pull the laptop's
    laptop.daemon.tick(force=True)
    server.daemon.tick(force=True)
    laptop.daemon.tick(force=True)
    yield server, laptop
    laptop.stop()
    server.stop()


def test_devices_know_each_other_after_introductions(pair):
    server, laptop = pair
    for a, b in ((server, "laptop"), (laptop, "server")):
        peers = a.admin.get("/admin/status").json()["peers"]
        assert [p["node_id"] for p in peers] == [b]
    assert server.admin.get("/admin/status").json()["cluster_id"] == \
        laptop.admin.get("/admin/status").json()["cluster_id"]


def test_put_replicates_evicts_and_reads_through(pair, tmp_path):
    server, laptop = pair
    data = os.urandom(60_000)
    digest = hashlib.sha256(data).hexdigest()

    r = server.admin.put("/admin/blob", params={"collection": "photos"}, content=data)
    assert r.status_code == 200 and r.json()["blob_hash"] == digest

    laptop.daemon.tick(force=True)                       # sees the fresh blob_stored, fetches it
    assert blob_path(laptop.root, digest).read_bytes() == data
    server.daemon.tick(force=True)                       # learns the laptop holds it

    server.command("evict_blob", blob_hash=digest, reason="pressure")
    assert not blob_path(server.root, digest).exists()   # dropped — the laptop provably has it

    got = server.admin.get(f"/admin/blob/{digest}")      # read-through: fetched back on demand
    assert got.status_code == 200 and got.content == data
    assert blob_path(server.root, digest).read_bytes() == data


def test_a_blob_nobody_has_is_404_not_a_hang(pair):
    server, _laptop = pair
    assert server.admin.get("/admin/blob/" + "ab" * 32).status_code == 404


def test_both_apis_demand_their_own_token(pair):
    server, _laptop = pair
    assert httpx.get(server.url + "/admin/status").status_code == 401
    assert httpx.get(server.url + "/peer/cluster").status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert httpx.get(server.url + "/peer/cluster", headers=wrong).status_code == 401
    # the peer token does not open the admin door, and vice versa
    assert httpx.get(server.url + "/admin/status",
                     headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 401
    assert httpx.get(server.url + "/peer/cluster",
                     headers={"Authorization": "Bearer " + server.daemon.device["admin_token"]}
                     ).status_code == 401


def test_admin_errors_are_reported_not_raised(pair):
    server, _laptop = pair
    r = server.admin.post("/admin/command", json={"name": "set_collection_policy",
        "fields": {"collection": "x", "min_sites": 0, "verify_max_age_days": 30, "evictable": True}})
    assert r.status_code == 400 and "min_sites" in r.json()["error"]
    assert server.admin.post("/admin/query", json={"name": "no_such_query"}).status_code == 400


def test_cli_put_and_get_round_trip(pair, tmp_path, capsys):
    server, _laptop = pair
    src = tmp_path / "hello.bin"
    src.write_bytes(os.urandom(5000))
    assert cli(["--root", str(server.root), "put", str(src), "--collection", "docs"]) == 0
    digest = capsys.readouterr().out.split()[0]
    assert digest == hashlib.sha256(src.read_bytes()).hexdigest()
    out = tmp_path / "back.bin"
    assert cli(["--root", str(server.root), "get", digest, "-o", str(out)]) == 0
    assert out.read_bytes() == src.read_bytes()


def test_state_survives_a_restart(pair, tmp_path):
    server, _laptop = pair
    data = os.urandom(1000)
    digest = server.admin.put("/admin/blob", params={"collection": "d"}, content=data).json()["blob_hash"]
    events_before = len(server.daemon.node.store)
    server.stop()

    again = Running(server.root)                       # same root: same identity and log
    try:
        assert len(again.daemon.node.store) == events_before
        assert again.daemon.node.epoch == server.daemon.node.epoch
        held = again.admin.post("/admin/query", json={"name": "get_node_usage",
                                                      "input": {"node_id": "server"}}).json()
        assert held["held_count"] == 1
        assert blob_path(again.root, digest).read_bytes() == data
    finally:
        again.stop()


def test_progress_logging_survives_a_full_buffer(pair, caplog):
    """The observation buffer is bounded; the daemon's log of it must not stall
    once it fills (it used to index the deque by position)."""
    import logging

    from dizzy_store.node import TELEMETRY_KEEP
    from gen_def.pydantic.telemetry import Progress

    server, _laptop = pair
    node = server.daemon.node
    server.daemon._log_progress()                       # catch up to now
    for i in range(TELEMETRY_KEEP + 50):                # overflow the buffer
        node._on_progress(Progress(stage="burst", detail=str(i)))
    server.daemon._log_progress()
    caplog.set_level(logging.INFO, logger="dizzy_store")
    node._on_progress(Progress(stage="after", detail="the-buffer-was-full"))
    server.daemon._log_progress()
    assert any("the-buffer-was-full" in r.getMessage() for r in caplog.records)


def test_the_daemon_path_needs_no_dev_dependencies():
    """The server installs with --no-dev. Importing the CLI/daemon/device must not
    pull in test-only packages (it once did, via a helper in the scenario runner)."""
    import subprocess
    import sys

    src = str(Path(__file__).resolve().parents[1] / "src")
    code = ("import sys\n"
            "for blocked in ('freezegun', 'pytest'):\n"
            "    sys.modules[blocked] = None\n"
            "import dizzy_store.cli, dizzy_store.daemon, dizzy_store.device\n"
            "print('imports ok')\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": src})
    assert result.returncode == 0 and "imports ok" in result.stdout, result.stderr


# ── details of what the daemon serves and the order it starts in ─────────────

def test_the_verify_endpoint_refuses_anything_that_is_not_a_hash(pair):
    server, laptop = pair
    peer = {"Authorization": f"Bearer {TOKEN}", "X-Peer-Id": "laptop"}
    for bad in ("not-a-hash", "..%2F..%2Fetc%2Fhostname", "A" * 64):
        r = httpx.get(f"{server.url}/peer/blob/{bad}/verify", headers=peer)
        assert r.status_code in (400, 404), (bad, r.status_code, r.text)
    good = httpx.get(f"{server.url}/peer/blob/{'0' * 64}/verify", headers=peer)
    assert good.status_code == 200 and good.json()["held"] is False


def test_the_peer_proof_rehashes_and_reports_the_live_card(pair):
    server, laptop = pair
    data = os.urandom(5_000)
    digest = server.admin.put("/admin/blob", params={"collection": "photos"}, content=data).json()["blob_hash"]
    peer = {"Authorization": f"Bearer {TOKEN}", "X-Peer-Id": "laptop"}
    proof = httpx.get(f"{server.url}/peer/blob/{digest}/verify", headers=peer).json()
    assert proof == {"held": True, "size": 5_000, "role": "hot", "draining": False}
    path = blob_path(server.root, digest)
    raw = bytearray(path.read_bytes())
    raw[0] ^= 0xFF
    path.write_bytes(bytes(raw))                           # rot it in place: same size
    proof = httpx.get(f"{server.url}/peer/blob/{digest}/verify", headers=peer).json()
    assert proof["held"] is False and proof["size"] == 5_000


def test_a_starting_device_reads_the_log_before_it_speaks(pair):
    """A device back from a wipe must see its previous life's announcement before it
    makes a new one, so the new one is stamped strictly after it."""
    server, laptop = pair
    calls = []
    daemon = laptop.daemon
    daemon.catch_up = lambda: calls.append("catch_up")
    daemon.announce = lambda: calls.append("announce")
    daemon.stop.set()                                      # run the start-up once, then fall out of the loop
    daemon.loop()
    assert calls == ["catch_up", "announce"]
