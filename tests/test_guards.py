"""A drive that goes away must stop the store, never be quietly replaced by an empty
directory: writing on would put blobs on the wrong disk (or in RAM) and record them as
stored. And a root that is not a store at start-up is a configuration problem, not a
reason to create one."""
import shutil
import threading

import httpx
import pytest

from conftest import ARCHIVE
from dizzy_store.cli import EX_CONFIG, main as cli
from dizzy_store.daemon import EX_IOERR, Daemon, serve
from dizzy_store.device import Device
from dizzy_store.http_sim import reserve_port
from dizzy_store.node import StoreNode
from storeutil import NotAStore, RootVanished, ensure_dir, place_atomic

H = "ab" + "cd" + "0" * 60


# ── the primitives ───────────────────────────────────────────────────────────

def test_place_atomic_never_recreates_a_vanished_root(tmp_path):
    src = tmp_path / "part"
    src.write_bytes(b"data")
    root = tmp_path / "mnt" / "store"                  # the drive was unplugged: no root, no .store
    with pytest.raises(RootVanished):
        place_atomic(src, root / "ab" / "cd" / H)
    assert not root.exists() and not (tmp_path / "mnt").exists()
    assert src.exists()                                # and the staged bytes were not consumed


def test_place_atomic_makes_the_shard_directories_when_the_root_is_there(tmp_path):
    (tmp_path / "root" / ".store").mkdir(parents=True)
    src = tmp_path / "part"
    src.write_bytes(b"data")
    place_atomic(src, tmp_path / "root" / "ab" / "cd" / H)
    assert (tmp_path / "root" / "ab" / "cd" / H).read_bytes() == b"data"


def test_ensure_dir_will_not_create_the_directory_it_is_told_must_exist(tmp_path):
    with pytest.raises(RootVanished):
        ensure_dir(tmp_path / "gone" / "tmp", below=tmp_path / "gone")
    assert not (tmp_path / "gone").exists()
    ensure_dir(tmp_path / "here" / "a" / "b", below=tmp_path)
    assert (tmp_path / "here" / "a" / "b").is_dir()


# ── the node ─────────────────────────────────────────────────────────────────

def test_a_real_device_will_not_conjure_its_own_root(tmp_path):
    with pytest.raises(NotAStore):
        StoreNode("x", tmp_path / "not-mounted", cluster_id=None, create_root=False)
    assert not (tmp_path / "not-mounted").exists()
    (tmp_path / "empty-mountpoint").mkdir()            # a mountpoint with nothing mounted on it
    with pytest.raises(NotAStore):
        StoreNode("x", tmp_path / "empty-mountpoint", cluster_id=None, create_root=False)
    assert list((tmp_path / "empty-mountpoint").iterdir()) == []


def test_a_vanished_root_stops_every_command_and_nothing_is_recreated(cluster_of):
    c = cluster_of(a=ARCHIVE)
    a = c.nodes["a"]
    a.edge_put([b"before"], "photos")
    shutil.rmtree(a.root)                              # the drive is yanked
    for attempt in (lambda: a.run("check_capacity"),
                    lambda: a.run("scrub_blobs", max_bytes=1 << 20),
                    lambda: a.edge_put([b"after"], "photos"),
                    lambda: a.drain()):
        try:
            attempt()
        except RootVanished:
            pass
        assert not a.root.exists(), "something recreated the vanished root"
    with pytest.raises(RootVanished):
        a.run("check_capacity")


def test_a_different_filesystem_at_the_same_path_is_detected(cluster_of):
    """Unplugged and a different drive (or the same one, re-enumerated) mounted there:
    `.store` exists but it is not the one this device started on."""
    c = cluster_of(a=ARCHIVE)
    a = c.nodes["a"]
    (a.root / ".store").rename(a.root / ".store-old")
    (a.root / ".store").mkdir()
    with pytest.raises(RootVanished):
        a.guard_root()


def test_an_intact_root_passes_the_guard_every_time(cluster_of):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    for _ in range(5):
        a.guard_root()


# ── the daemon ───────────────────────────────────────────────────────────────

@pytest.fixture
def device(tmp_path):
    root = tmp_path / "dev"
    assert cli(["--root", str(root), "init", "--node-id", "d", "--role", "archive", "--site", "lab",
                "--wants", "*", "--limit-bytes", "1GB"]) == 0
    assert cli(["--root", str(root), "found"]) == 0
    return root


def test_the_daemon_stops_with_an_io_error_when_its_drive_goes_away(device):
    daemon = Daemon(Device.load(device))
    daemon.tick(force=True)                            # healthy
    assert daemon.exit_code == 0 and not daemon.stop.is_set()
    daemon.node.close()
    shutil.rmtree(device)
    daemon.tick(force=True)
    assert daemon.exit_code == EX_IOERR == 74
    assert daemon.stop.is_set()
    assert not device.exists(), "the daemon recreated the root it lost"


def test_serve_returns_the_exit_status_and_stops_the_server(device):
    daemon = Daemon(Device.load(device))
    sock = reserve_port()
    done = {}
    thread = threading.Thread(target=lambda: done.update(code=serve(daemon, sockets=[sock])), daemon=True)
    thread.start()
    for _ in range(100):                               # wait until the HTTP server is answering
        try:
            if httpx.get(f"http://127.0.0.1:{sock.getsockname()[1]}/peer/cluster", timeout=1).status_code:
                break
        except httpx.HTTPError:
            threading.Event().wait(0.05)
    daemon.fatal(RootVanished("the drive was unplugged"))
    thread.join(timeout=15)
    assert not thread.is_alive(), "serve() did not stop"
    assert done["code"] == EX_IOERR


def test_an_ordinary_stop_exits_zero(device):
    daemon = Daemon(Device.load(device))
    sock = reserve_port()
    done = {}
    thread = threading.Thread(target=lambda: done.update(code=serve(daemon, sockets=[sock])), daemon=True)
    thread.start()
    threading.Event().wait(0.5)
    daemon.server.should_exit = True                   # what SIGTERM does
    thread.join(timeout=15)
    assert done["code"] == 0


# ── the command line ─────────────────────────────────────────────────────────

def test_a_root_that_is_not_a_store_is_a_configuration_error(tmp_path, capsys):
    for command in (["run"], ["status"], ["found"]):
        assert cli(["--root", str(tmp_path / "unmounted"), *command]) == EX_CONFIG == 78
    assert not (tmp_path / "unmounted").exists()
    assert "not a store device" in capsys.readouterr().err
