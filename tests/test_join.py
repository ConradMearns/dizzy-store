"""`join` puts a NEW store into a cluster. It must never move an existing store out of its own: that would merge
two event logs, and a merged log cannot be pulled apart again (think of a store holding someone else's files)."""
import pytest

from dizzy_store.cli import EX_CONFIG, main as cli
from dizzy_store.device import Device
from test_daemon import TOKEN, Running


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "server"
    assert cli(["--root", str(root), "init", "--node-id", "server", "--role", "hot", "--site", "hetzner",
                "--limit-bytes", "100KB", "--peer-token", TOKEN]) == 0
    assert cli(["--root", str(root), "found", "--cluster-id", "yours"]) == 0
    running = Running(root)
    yield running
    running.stop()


def make_store(root, name, *, found=None):
    # the SAME peer token as the server's: the dangerous case, a copy-paste slip — the token alone must not be enough
    assert cli(["--root", str(root), "init", "--node-id", name, "--role", "archive", "--site", "home",
                "--wants", "*", "--limit-bytes", "1GB", "--peer-token", TOKEN]) == 0
    if found:
        assert cli(["--root", str(root), "found", "--cluster-id", found]) == 0


def test_a_store_that_belongs_to_another_cluster_is_refused_and_left_exactly_as_it_was(server, tmp_path, capsys):
    gma = tmp_path / "gma"
    make_store(gma, "gma", found="gma")
    before = (gma / ".store" / "device.json").read_bytes()
    capsys.readouterr()
    assert cli(["--root", str(gma), "join", "--url", server.url]) == EX_CONFIG
    err = capsys.readouterr().err
    assert "'gma'" in err and "'yours'" in err and "merge" in err
    assert (gma / ".store" / "device.json").read_bytes() == before            # not one byte changed
    assert Device.load(gma)["cluster_id"] == "gma"


def test_a_new_store_joins_and_may_join_again_to_record_a_route_from_somewhere_else(server, tmp_path, monkeypatch):
    new = tmp_path / "new"
    make_store(new, "new")
    assert cli(["--root", str(new), "join", "--url", server.url]) == 0
    assert Device.load(new)["cluster_id"] == "yours"
    monkeypatch.setenv("DIZZY_STORE_HOST", "another-computer")                  # a portable drive, plugged in elsewhere
    assert Device.load(new)["seeds"] == {}
    assert cli(["--root", str(new), "join", "--url", server.url]) == 0          # the SAME cluster: always fine
    assert Device.load(new)["seeds"] == {"server": server.url}
