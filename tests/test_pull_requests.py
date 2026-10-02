"""A peer's "pull from me" request is the SIDE door through which another device's events can reach a store. It must
apply the same rule as the front door (`sync_peer`): events are merged only between devices of ONE cluster.

The dangerous case is an accident, so every store here shares ONE peer token — the token alone must not be enough."""
import httpx
import pytest

from conftest import events_of
from dizzy_store.cli import main as cli
from test_daemon import TOKEN, Running


@pytest.fixture
def start(tmp_path):
    running = []

    def make(name, *, cluster=None, join=None):
        root = tmp_path / name
        assert cli(["--root", str(root), "init", "--node-id", name, "--role", "archive", "--site", "home",
                    "--wants", "*", "--limit-bytes", "1GB", "--peer-token", TOKEN]) == 0
        if cluster:
            assert cli(["--root", str(root), "found", "--cluster-id", cluster]) == 0
        if join:
            assert cli(["--root", str(root), "join", "--url", join.url]) == 0
        running.append(Running(root))
        return running[-1]

    yield make
    for r in running:
        r.stop()


def knock(on: Running, who: Running) -> None:
    """What a peer's request_pull sends — by hand, with the shared token, as a slip or a hostile peer would."""
    name = who.daemon.node.name
    response = httpx.post(f"{on.url}/peer/pull-request", json={"requester": name, "endpoints": [who.url]},
                          headers={"Authorization": f"Bearer {TOKEN}", "X-Peer-Id": name})
    assert response.status_code == 202                       # the door opens; whether to ACT on it is decided later


def refusals(r: Running) -> list[str]:
    return [p.detail for p in r.daemon.node.progress if p.stage == "pull_refused"]


def test_a_knock_from_another_cluster_is_refused_and_merges_nothing(start):
    yours, gma = start("yours", cluster="yours"), start("gma", cluster="gma")
    assert events_of(gma.daemon.node, "node_announced", by="gma")      # gma has news to offer
    before = len(yours.daemon.node.store)
    knock(yours, gma)
    yours.daemon.node.drain()
    assert events_of(yours.daemon.node, "node_announced", by="gma") == []      # not one of gma's events arrived
    assert len(yours.daemon.node.store) == before
    assert len(refusals(yours)) == 1 and "'gma'" in refusals(yours)[0] and "'yours'" in refusals(yours)[0]
    peers = yours.daemon.node.peers
    assert "gma" not in peers._hints and "gma" not in peers._last_good        # and its address is not remembered


def test_a_knock_from_a_device_of_the_same_cluster_is_still_serviced(start):
    yours = start("yours", cluster="yours")
    newer = start("newer", join=yours)
    newer.daemon.node.announce()
    knock(yours, newer)
    yours.daemon.node.drain()
    assert events_of(yours.daemon.node, "node_announced", by="newer")
    assert refusals(yours) == []


def test_a_store_that_has_not_joined_any_cluster_takes_nothing(start, monkeypatch):
    nowhere, other = start("nowhere"), start("other")                 # initialised, never founded or joined
    pulled = []
    monkeypatch.setattr(nowhere.daemon.node, "pull_from_peer", lambda peer: pulled.append(peer) or 0)
    knock(nowhere, other)
    nowhere.daemon.node.drain()
    assert pulled == [] and "this device has not joined a cluster" in refusals(nowhere)[0]


def test_a_knock_from_a_device_with_no_cluster_is_refused_too(start, monkeypatch):
    yours, stray = start("yours", cluster="yours"), start("stray")     # stray never founded or joined
    pulled = []
    monkeypatch.setattr(yours.daemon.node, "pull_from_peer", lambda peer: pulled.append(peer) or 0)
    knock(yours, stray)
    yours.daemon.node.drain()
    assert pulled == [] and "it has not joined a cluster" in refusals(yours)[0]


def test_a_knocker_that_has_gone_away_is_dropped_quietly(start):
    yours, gone = start("yours", cluster="yours"), start("gone", cluster="yours")
    knock(yours, gone)
    gone.stop()                                                        # it knocked, then vanished
    yours.daemon.node.drain()                                          # must not raise
    assert refusals(yours) == []
