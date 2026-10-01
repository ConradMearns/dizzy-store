"""The small pieces of the transport that scenarios don't isolate."""
import hashlib

import pytest

from dizzy_store.antientropy import bucket_digests, reconcile_pull
from dizzy_store.peer_http import parse_range
from dizzy_store.sim import SimCluster
from storeutil import Throttle


# ── byte ranges (chunked fetches ask for these) ──────────────────────────────

@pytest.mark.parametrize("header, size, expected", [
    ("bytes=0-99", 1000, (0, 99)),
    ("bytes=900-", 1000, (900, 999)),
    ("bytes=-100", 1000, (900, 999)),
    ("bytes=990-5000", 1000, (990, 999)),          # clipped to the file
    ("", 1000, None),
    ("bytes=-", 1000, None),
    ("items=0-5", 1000, None),
])
def test_parse_range(header, size, expected):
    assert parse_range(header, size) == expected


@pytest.mark.parametrize("header, size", [("bytes=1000-", 1000), ("bytes=5-2", 1000),
                                           ("bytes=0-0", 0)])
def test_unsatisfiable_ranges_raise(header, size):
    with pytest.raises(ValueError):
        parse_range(header, size)


# ── set reconciliation ───────────────────────────────────────────────────────

def _two_nodes(tmp_path):
    cluster = SimCluster(tmp_path)
    a = cluster.found("a")
    b = cluster.add_node("b")
    return cluster, a, b


def test_reconcile_moves_exactly_what_is_missing(tmp_path):
    _cluster, a, b = _two_nodes(tmp_path)
    for n in range(30):
        a.run("set_collection_policy", collection=f"c{n}", min_sites=1,
              verify_max_age_days=30, evictable=True)
    b.run("set_collection_policy", collection="b-only", min_sites=1,
          verify_max_age_days=30, evictable=True)

    pulled = reconcile_pull(b.store, a.surface, batch=7)        # several batches
    assert len(pulled) == 31                                    # a's 30 + a's create_cluster
    assert reconcile_pull(b.store, a.surface) == []             # now identical on a's side
    assert a.store.dag.ids() <= b.store.dag.ids()


def test_buckets_both_sides_hold_with_different_events_are_reconciled(tmp_path):
    """Two 200-event logs share most of their 256 buckets but not their events: a digest
    that ignored content would see "same bucket" and move nothing."""
    _cluster, a, b = _two_nodes(tmp_path)
    for n in range(200):
        a.run("set_collection_policy", collection=f"a{n}", min_sites=1,
              verify_max_age_days=30, evictable=True)
        b.run("set_collection_policy", collection=f"b{n}", min_sites=1,
              verify_max_age_days=30, evictable=True)
    shared = set(bucket_digests(a.store)) & set(bucket_digests(b.store))
    assert len(shared) > 50                                     # the premise of the test
    pulled = reconcile_pull(b.store, a.surface, batch=64)
    assert len(pulled) == 201                                   # a's 200 + a's create_cluster
    assert a.store.dag.ids() <= b.store.dag.ids()
    assert bucket_digests(b.store) != bucket_digests(a.store)   # b still has its own 200


def test_identical_logs_cost_one_digest_exchange(tmp_path):
    _cluster, a, b = _two_nodes(tmp_path)
    reconcile_pull(b.store, a.surface)
    reconcile_pull(a.store, b.surface)
    assert bucket_digests(a.store) == bucket_digests(b.store)
    calls = []

    class Counting:
        def __init__(self, inner):
            self.inner = inner

        def buckets(self):
            calls.append("buckets")
            return self.inner.buckets()

        def ids(self, prefixes):
            calls.append("ids")
            return self.inner.ids(prefixes)

        def events(self, ids):
            calls.append("events")
            return self.inner.events(ids)

    assert reconcile_pull(b.store, Counting(a.surface)) == []
    assert calls == ["buckets"]                                 # nothing else was asked


def test_a_wiped_device_pulls_the_whole_log(tmp_path):
    _cluster, a, b = _two_nodes(tmp_path)
    for n in range(10):
        a.run("set_collection_policy", collection=f"c{n}", min_sites=1,
              verify_max_age_days=30, evictable=True)
    b.wipe()
    assert len(reconcile_pull(b.store, a.surface, batch=4)) == len(a.store)


# ── the throttle ─────────────────────────────────────────────────────────────

def test_throttle_is_off_at_zero_and_paces_otherwise():
    slept = []
    clock = [0.0]
    off = Throttle(0, clock=lambda: clock[0], sleep=slept.append)
    off.wait(10**9)
    assert slept == []

    t = Throttle(1000, clock=lambda: clock[0], sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
    t.wait(1000)            # the bucket starts with one second's worth of budget
    assert slept == []
    t.wait(500)             # now 500 bytes in debt at 1000 B/s -> half a second
    assert slept and abs(slept[-1] - 0.5) < 1e-9
