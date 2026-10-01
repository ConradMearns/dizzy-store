"""`run --until-idle`: plug in, sync, unplug. It may say "up to date" only when that is TRUE.

Real daemons on real sockets (a server that keeps ticking, and the drive's daemon run through `serve`), so
"the peer cannot reach back", "nobody holds the blob" and "the peer is gone" are the real failure modes.
"""
import hashlib
import json
import os
import socket
import threading
import time

import pytest

from conftest import events_of
from dizzy_store import cli as cli_module
from dizzy_store.cli import main as cli
from dizzy_store.daemon import Daemon, IdlePolicy, serve
from dizzy_store.device import Device
from dizzy_store.exitcodes import EX_CONFIG, EX_TEMPFAIL
from storeutil import blob_path
from test_daemon import TOKEN, Running

QUICK = dict(settle_s=0.8, grace_s=3.0, stall_s=3.0, report_s=60.0, max_s=60.0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def init_drive(root, *, endpoint=True):
    port = free_port()
    args = ["--root", str(root), "init", "--node-id", "drive", "--role", "archive", "--site", "home",
            "--wants", "*", "--limit-bytes", "10MB", "--peer-token", TOKEN, "--listen", f"127.0.0.1:{port}"]
    if endpoint:
        args += ["--endpoint", f"http://127.0.0.1:{port}"]      # where the server can reach it back
    assert cli(args) == 0


@pytest.fixture
def cluster(tmp_path):
    """A server that keeps ticking (so it services pull requests), and a drive that is not running yet."""
    server_root, drive_root = tmp_path / "server", tmp_path / "drive"
    assert cli(["--root", str(server_root), "init", "--node-id", "server", "--role", "hot", "--site", "hetzner",
                "--limit-bytes", "1MB", "--peer-token", TOKEN]) == 0
    assert cli(["--root", str(server_root), "found"]) == 0
    server = Running(server_root)
    ticking = threading.Thread(target=server.daemon.loop, daemon=True)
    ticking.start()

    def make_drive(**kwargs):
        init_drive(drive_root, **kwargs)
        assert cli(["--root", str(drive_root), "join", "--url", server.url]) == 0
        return drive_root

    yield server, make_drive
    server.daemon.stop.set()
    ticking.join(timeout=10)
    server.stop()


def put(server, size=3000, collection="photos") -> tuple[str, bytes]:
    data = os.urandom(size)
    response = server.admin.put("/admin/blob", params={"collection": collection}, content=data)
    assert response.status_code == 200
    return hashlib.sha256(data).hexdigest(), data


def test_a_caught_up_drive_stops_with_success_holding_everything_and_known_to_the_cluster(cluster):
    server, make_drive = cluster
    blobs = dict(put(server, 3000 + i) for i in range(3))
    root = make_drive()
    daemon = Daemon(Device.load(root))
    code = serve(daemon, idle=IdlePolicy(**QUICK))
    assert code == 0, daemon.idle_result
    assert daemon.idle_result[1].startswith("up to date") and "in step with server" in daemon.idle_result[1]
    for blob_hash, data in blobs.items():
        assert blob_path(root, blob_hash).read_bytes() == data
    assert daemon.in_step == {"server"}
    # and the cluster KNOWS the drive holds them: the push half, not just the pull half
    told = {e["blob_hash"] for e in events_of(server.daemon.node, "blob_stored", by="drive")}
    assert told == set(blobs)


def test_an_empty_cluster_is_up_to_date_too(cluster):
    _server, make_drive = cluster
    daemon = Daemon(Device.load(make_drive()))
    assert serve(daemon, idle=IdlePolicy(**QUICK)) == 0
    assert daemon.idle_result[1].startswith("up to date")


def test_it_does_not_call_a_run_up_to_date_while_blobs_are_still_coming(cluster):
    server, make_drive = cluster
    for i in range(12):
        put(server, 2000 + i)
    root = make_drive()
    daemon = Daemon(Device.load(root))
    daemon.node.env_store.max_dispatch_per_event = 2         # a paced sweep: a few blobs per pass
    assert serve(daemon, idle=IdlePolicy(**QUICK)) == 0
    assert daemon.node.query("get_node_usage", node_id="drive").held_count == 12      # ALL of them, not the first pass's
    assert daemon.idle_result[1].startswith("up to date")
    assert daemon.passes > 3                                 # it took several passes, and waited for all of them


def test_a_peer_that_cannot_be_reached_is_a_retry_later_not_success(cluster):
    server, make_drive = cluster
    put(server)
    root = make_drive()
    server.daemon.stop.set()
    server.stop()                                            # the cluster goes away after the join
    daemon = Daemon(Device.load(root))
    code = serve(daemon, idle=IdlePolicy(**{**QUICK, "grace_s": 1.5}))
    assert code == EX_TEMPFAIL == 75
    assert "reached no peer" in daemon.idle_result[1]
    assert "server" in daemon.idle_result[1]                 # and it says WHICH peers it tried


def test_a_peer_that_answers_but_cannot_reach_back_is_not_in_step(cluster):
    """The usual home-network shape: the drive can call the server, the server cannot call the drive. The
    drive pulls everything — but the server never learns what the drive holds, so "up to date" would be a lie."""
    server, make_drive = cluster
    put(server)
    root = make_drive(endpoint=False)
    dev = Device.load(root)
    dev.remember("endpoints", ["http://127.0.0.1:1"])        # an address the server cannot use
    dev.save()
    daemon = Daemon(Device.load(root))
    code = serve(daemon, idle=IdlePolicy(**{**QUICK, "stall_s": 2.0}))
    assert code == EX_TEMPFAIL
    assert "cannot get in step" in daemon.idle_result[1] and "reach back" in daemon.idle_result[1]
    assert daemon.reached == {"server"} and daemon.in_step == set()


def test_blobs_nobody_can_supply_are_reported_not_waited_for_forever(cluster):
    server, make_drive = cluster
    blob_hash, _ = put(server)
    blob_path(server.root, blob_hash).unlink()               # the log says the server holds it; the disk disagrees
    daemon = Daemon(Device.load(make_drive()))
    code = serve(daemon, idle=IdlePolicy(**QUICK))
    assert code == EX_TEMPFAIL
    assert "1 wanted blobs could not be fetched" in daemon.idle_result[1]


def test_an_overall_ceiling_ends_a_run_that_is_not_getting_anywhere(cluster):
    server, make_drive = cluster
    put(server)
    root = make_drive(endpoint=False)
    dev = Device.load(root)
    dev.remember("endpoints", ["http://127.0.0.1:1"])
    dev.save()
    daemon = Daemon(Device.load(root))
    code = serve(daemon, idle=IdlePolicy(**{**QUICK, "stall_s": 60.0, "max_s": 2.0}))
    assert code == EX_TEMPFAIL and daemon.idle_result[1].startswith("gave up after 2s")


def test_a_drive_that_vanishes_during_the_run_is_an_io_error_not_a_verdict(cluster, tmp_path):
    server, make_drive = cluster
    root = make_drive()
    daemon = Daemon(Device.load(root))
    threading.Timer(1.5, lambda: daemon.fatal(RuntimeError("the drive is gone"))).start()
    code = serve(daemon, idle=IdlePolicy(**{**QUICK, "settle_s": 30.0}))
    assert code == 74 and daemon.idle_result is None


def test_a_route_learned_by_join_belongs_to_the_computer_that_learned_it(cluster, monkeypatch):
    server, make_drive = cluster
    root = make_drive()
    assert Device.load(root)["seeds"] == {"server": server.url}
    on_drive = json.loads((root / ".store" / "device.json").read_text())
    assert on_drive["seeds"] == {}                         # nothing machine-specific in the part every computer reads
    monkeypatch.setenv("DIZZY_STORE_HOST", "some-other-computer")
    assert Device.load(root)["seeds"] == {}                # plugged in elsewhere, it has no route to the server yet


# ── the command line ─────────────────────────────────────────────────────────

@pytest.fixture
def ejects(monkeypatch):
    """Stand in for a removable drive: record what `--eject` asks the system to do."""
    calls = []

    def fake(root, name, *, dry_run=False, say=print, **kwargs):
        calls.append(("preflight" if dry_run else "eject", str(root), name))
        return 0

    monkeypatch.setattr(cli_module, "run_eject", fake)
    return calls


def test_the_command_ejects_only_after_a_run_that_really_finished(cluster, ejects, capsys, tmp_path, monkeypatch):
    server, make_drive = cluster
    put(server)
    root = make_drive()
    monkeypatch.chdir(tmp_path)                              # the command leaves the drive's tree (cwd "/") before it ejects;
    assert cli(["--root", str(root), "run", "--until-idle", "--eject", "--wait", "60"]) == 0
    out = capsys.readouterr().out
    assert "up to date" in out
    assert [kind for kind, *_ in ejects] == ["preflight", "eject"]
    assert ejects[1][1] == str(root.resolve())


def test_the_command_does_not_eject_a_drive_it_could_not_finish_with(cluster, ejects, capsys):
    server, make_drive = cluster
    root = make_drive()
    server.daemon.stop.set()
    server.stop()
    assert cli(["--root", str(root), "run", "--until-idle", "--eject", "--wait", "6"]) == EX_TEMPFAIL
    assert [kind for kind, *_ in ejects] == ["preflight"]            # nothing was ejected
    err = capsys.readouterr().err
    assert err.startswith("gave up after 6s") and "not answering server" in err


def test_eject_is_refused_up_front_for_a_store_that_is_not_on_a_removable_drive(cluster, capsys):
    _server, make_drive = cluster
    root = make_drive()
    assert cli(["--root", str(root), "run", "--until-idle", "--eject"]) == EX_CONFIG       # real run_eject: tmp is not USB
    err = capsys.readouterr().err
    assert "--eject is for a store on a removable drive" in err
    assert not (root / ".store" / "daemon.lock").exists()             # and it never started anything


def test_a_device_that_has_not_finished_stopping_is_neither_closed_nor_unmounted(tmp_path, ejects, capsys, monkeypatch):
    """If the tick thread is still busy when the server stops (a long transfer), closing the databases under it or
    unmounting the drive under it would be the worst moment to do either."""
    root = tmp_path / "drive"
    init_drive(root)
    assert cli(["--root", str(root), "found"]) == 0
    seen = []

    def stuck(daemon, **kwargs):
        seen.append(daemon)
        daemon.idle_result = (0, "up to date — stubbed")
        daemon.loop_done = False                         # the tick thread is still busy
        return 0

    monkeypatch.setattr("dizzy_store.daemon.serve", stuck)
    assert cli(["--root", str(root), "run", "--until-idle", "--eject"]) == EX_TEMPFAIL
    assert [kind for kind, *_ in ejects] == ["preflight"]            # not unmounted
    assert "still busy" in capsys.readouterr().err
    assert len(seen[0].node.store) >= 1                              # and not closed: its event log still answers


def test_serve_says_so_when_the_tick_thread_has_not_stopped(tmp_path, monkeypatch, caplog):
    root = tmp_path / "drive"
    init_drive(root)
    assert cli(["--root", str(root), "found"]) == 0
    daemon = Daemon(Device.load(root))
    entered = threading.Event()

    def slow_tick(self, force=False):                        # a transfer in flight: the tick thread is busy for a while
        entered.set()
        time.sleep(2.0)

    def stop_when_busy():
        entered.wait(10)
        daemon.stop.set()
        daemon.server.should_exit = True

    monkeypatch.setattr(Daemon, "tick", slow_tick)
    threading.Thread(target=stop_when_busy, daemon=True).start()
    assert serve(daemon, stop_wait=0.3) == 0
    assert daemon.loop_done is False and "still busy after 0.3s" in caplog.text
    time.sleep(2.2)                                          # let the tick thread finish before anything is torn down


def test_serve_says_the_tick_thread_has_stopped_when_it_has(tmp_path):
    root = tmp_path / "drive"
    init_drive(root)
    assert cli(["--root", str(root), "found"]) == 0
    daemon = Daemon(Device.load(root))
    threading.Timer(1.5, lambda: (daemon.stop.set(), setattr(daemon.server, "should_exit", True))).start()
    assert serve(daemon) == 0 and daemon.loop_done is True
