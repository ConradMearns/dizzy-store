"""The sweep's memory: how long it waits after a failure, and what clears it."""
from datetime import datetime, timedelta, timezone

from freezegun import freeze_time

from conftest import ARCHIVE, IDLE, events_of, sync_both
from dizzy_store.sweep import BACKOFF_BASE_S, BACKOFF_MAX_S, sweep
from storeutil import blob_path

START = "2026-01-01T00:00:00"


def unfetchable(cluster_of, **cfg):
    """b wants everything; the only holder claims the blob but has lost its bytes."""
    c = cluster_of(a=ARCHIVE, b=ARCHIVE)
    if cfg:
        c.nodes["b"].config.update(cfg)
    h = c.nodes["a"].edge_put([b"payload" * 100], "photos")
    blob_path(c.nodes["a"].root, h).unlink()
    return c, h


def attempts(node):
    return len([f for f in events_of(node, "blob_replication_failed", by="b")])


def test_failures_back_off_exponentially_then_cap(cluster_of):
    with freeze_time(START) as clock:
        c, h = unfetchable(cluster_of)
        b = c.nodes["b"]
        sync_both(c, "a", "b")                               # (the fresh announcement draws one policy attempt)
        base = attempts(b)
        clock.tick(timedelta(hours=2))                       # now it is stale news: the sweep's job
        waits = []
        for expected in (60, 120, 240, 480):
            sweep(b)
            fails, retry_after = b.sweep_state[("replicate", h)]
            waits.append((fails, (retry_after.replace(tzinfo=None) - clock().replace(tzinfo=None)).total_seconds()))
            clock.tick(timedelta(seconds=expected + 1))
        assert waits == [(1, 60), (2, 120), (3, 240), (4, 480)]
        assert attempts(b) == base + 4
        sweep(b), sweep(b)                                   # the first is due again; the second is inside its window
        assert attempts(b) == base + 5


def test_the_wait_never_exceeds_the_cap(cluster_of):
    with freeze_time(START) as clock:
        c, h = unfetchable(cluster_of)
        b = c.nodes["b"]
        sync_both(c, "a", "b")
        clock.tick(timedelta(hours=2))
        b.sweep_state[("replicate", h)] = (40, datetime.now(timezone.utc) - timedelta(seconds=1))
        sweep(b)
        fails, retry_after = b.sweep_state[("replicate", h)]
        assert fails == 41
        assert (retry_after - datetime.now(timezone.utc)).total_seconds() == BACKOFF_MAX_S


def test_a_success_clears_the_memory(cluster_of):
    with freeze_time(START) as clock:
        c, h = unfetchable(cluster_of)
        b = c.nodes["b"]
        sync_both(c, "a", "b")
        clock.tick(timedelta(hours=2))
        sweep(b)
        assert ("replicate", h) in b.sweep_state
        # the holder gets its bytes back (a repair), and the retry window passes
        data = b"payload" * 100
        path = blob_path(c.nodes["a"].root, h)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        clock.tick(timedelta(seconds=BACKOFF_BASE_S + 1))
        assert sweep(b)["replicated"] == 1
        assert ("replicate", h) not in b.sweep_state


def test_a_zero_cap_means_one_not_everything(cluster_of):
    with freeze_time(START) as clock:
        c = cluster_of(a=ARCHIVE, b=ARCHIVE)
        c.nodes["b"].env_store.max_dispatch_per_event = 0
        for n in range(5):
            c.nodes["a"].edge_put([bytes([n]) * 300], "photos")
        sync_both(c, "a", "b")
        clock.tick(timedelta(hours=2))                       # stale: only the sweep acts
        held = lambda: c.nodes["b"].query("get_node_usage", node_id="b").held_count
        start = held()
        sweep(c.nodes["b"])
        assert held() - start == 1


def test_a_draining_node_is_never_a_replication_target(cluster_of):
    """Not even for a moment: a sweep that fetched a blob and evicted it again in the same
    tick would leave the same bytes on disk but churn the log (and the uplink)."""
    c = cluster_of(srv={"role": "hot", "wants": []}, laptop=ARCHIVE, nas=ARCHIVE)
    c.nodes["srv"].edge_put([b"first" * 100], "photos")
    sync_both(c, "srv", "laptop")
    sync_both(c, "srv", "nas")
    laptop = c.nodes["laptop"]
    laptop.announce(draining=True)
    sync_both(c, "laptop", "srv")
    sweep(laptop)
    stored_before = len(events_of(laptop, "blob_stored", by="laptop"))
    evicted_before = len(events_of(laptop, "blob_evicted", by="laptop"))
    c.nodes["srv"].edge_put([b"second" * 100], "photos")
    sync_both(c, "srv", "laptop")
    sweep(laptop)
    assert len(events_of(laptop, "blob_stored", by="laptop")) == stored_before
    assert len(events_of(laptop, "blob_evicted", by="laptop")) == evicted_before
