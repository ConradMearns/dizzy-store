"""min_evict_bytes (principle 11): under pressure a blob smaller than it is never evicted — whoever asks
(the pressure policy, the paced sweep, a command issued by hand) — while a draining node still empties itself.

The rule lives in two places that must agree: the candidates query (so relief never counts or tries an exempt
blob) and evict_blob (so a hand-issued command cannot get around it)."""
from datetime import timedelta
from types import SimpleNamespace

from freezegun import freeze_time

from conftest import ARCHIVE, HOT, events_of, sync_both
from dizzy_store import invariants
from dizzy_store.sweep import sweep

KB = 1024
START = "2026-01-01T00:00:00"
NOTHING = {"replicated": 0, "evicted": 0, "failed": 0}


def pool(cluster_of, clock, *, smallest, sizes):
    """A hot server holding blobs of the given sizes (oldest first, a minute apart), every one of them also on an
    archive — so each is provably safe to drop and only the exemption can stop it."""
    c = cluster_of(srv=HOT, laptop=ARCHIVE)
    srv = c.nodes["srv"]
    hashes = []
    for i, size in enumerate(sizes):
        hashes.append(srv.edge_put([bytes([i + 1]) * size], "photos"))
        clock.tick(timedelta(minutes=1))
    sync_both(c, "srv", "laptop")
    laptop = c.nodes["laptop"]
    while sweep(laptop)["replicated"]:                 # a merge reacts to a bounded number of arrivals (principle 9)
        pass                                           # — the sweep brings the archive the rest
    sync_both(c, "srv", "laptop")                      # ... and the server hears what the archive now holds
    assert all(laptop.has_blob(h) for h in hashes), "the archive must hold every blob, or the proof is what refuses"
    srv.env_store.min_evict_bytes = smallest
    return c, srv, laptop, hashes


def squeeze(node, limit=10 * KB, high=0.8, low=0.5):
    """Put the node over its watermark (set AFTER the uploads, so nothing reacts while the pool is built)."""
    node.env_store.limit_bytes = limit
    node.env_store.high_watermark = high
    node.env_store.low_watermark = low


def sizes_of(node, **inputs):
    return node.query("get_eviction_candidates", node_id=node.name, **inputs).byte_sizes


# ── the candidates query ─────────────────────────────────────────────────────

def test_candidates_skip_blobs_under_min_bytes_and_a_blob_exactly_that_size_is_one(cluster_of):
    with freeze_time(START) as clock:
        _c, srv, _laptop, _hs = pool(cluster_of, clock, smallest=0, sizes=[1999, 2000, 2001])
        assert sizes_of(srv, min_bytes=2000) == [2000, 2001]        # one under is exempt; exactly the threshold is not
        assert sizes_of(srv) == [1999, 2000, 2001]                  # no input: no exemption (every existing caller)
        assert sizes_of(srv, min_bytes=0) == [1999, 2000, 2001]
        assert sizes_of(srv, min_bytes=2002) == []                  # everything is under it


def test_exempt_blobs_count_toward_neither_what_is_needed_nor_the_limit(cluster_of):
    with freeze_time(START) as clock:
        # the three OLDEST are exempt; two eligible blobs follow
        _c, srv, _laptop, _hs = pool(cluster_of, clock, smallest=0, sizes=[500, 600, 700, 3000, 3100])
        assert sizes_of(srv, min_bytes=1000, limit=1) == [3000]              # the exempt head does not use the limit up
        assert sizes_of(srv, min_bytes=1000, limit=2) == [3000, 3100]
        assert sizes_of(srv, min_bytes=1000, bytes_needed=3500) == [3000, 3100]   # 1800 exempt bytes did not "cover" it
        assert sizes_of(srv, min_bytes=1000, bytes_needed=2500) == [3000]


def test_a_draining_node_is_offered_its_small_blobs_too(cluster_of):
    c = cluster_of(srv=HOT, laptop=ARCHIVE, nas=ARCHIVE)
    small = c.nodes["srv"].edge_put([b"s" * 100], "photos")
    big = c.nodes["srv"].edge_put([b"b" * 3000], "photos")
    for peer in ("laptop", "nas"):
        sync_both(c, "srv", peer)
    laptop = c.nodes["laptop"]
    laptop.env_store.min_evict_bytes = 10 ** 9
    laptop.announce(draining=True)
    sync_both(c, "laptop", "nas")
    sync_both(c, "laptop", "srv")
    offered = laptop.query("get_eviction_candidates", node_id="laptop", min_bytes=10 ** 9).blob_hashes
    assert sorted(offered) == sorted([small, big])                  # leaving means leaving


# ── evict_blob, asked by hand ────────────────────────────────────────────────

def test_evict_blob_refuses_a_small_blob_under_pressure_even_when_asked_by_hand(cluster_of):
    with freeze_time(START) as clock:
        _c, srv, laptop, (under, exactly, over) = pool(cluster_of, clock, smallest=2000, sizes=[1999, 2000, 2001])
        srv.run("evict_blob", blob_hash=under, reason="pressure")
        assert srv.has_blob(under)
        assert events_of(srv, "blob_evicted", by="srv") == []                      # nothing was recorded
        refusals = [p for p in srv.progress if p.stage == "evict_refused" and under[:12] in p.detail]
        assert refusals and "min_evict_bytes" in refusals[-1].detail and "1999" in refusals[-1].detail
        srv.run("evict_blob", blob_hash=exactly, reason="pressure")
        srv.run("evict_blob", blob_hash=over, reason="pressure")
        assert not srv.has_blob(exactly) and not srv.has_blob(over)                # exactly the threshold goes
        assert all(laptop.has_blob(h) for h in (under, exactly, over))             # and every byte is still safe


def test_without_the_setting_nothing_is_exempt(cluster_of):
    with freeze_time(START) as clock:
        _c, srv, _laptop, (tiny,) = pool(cluster_of, clock, smallest=0, sizes=[10])
        srv.run("evict_blob", blob_hash=tiny, reason="pressure")
        assert not srv.has_blob(tiny)                                              # today's behaviour, unchanged


def test_a_drain_evicts_small_blobs_despite_the_threshold(cluster_of):
    c = cluster_of(srv=HOT, laptop=ARCHIVE, nas=ARCHIVE)
    small = c.nodes["srv"].edge_put([b"s" * 100], "photos")
    for peer in ("laptop", "nas"):
        sync_both(c, "srv", peer)
    laptop = c.nodes["laptop"]
    laptop.env_store.min_evict_bytes = 10 ** 9
    laptop.announce(draining=True)
    sync_both(c, "laptop", "nas")
    laptop.run("evict_blob", blob_hash=small, reason="drain")
    assert not laptop.has_blob(small) and c.nodes["nas"].has_blob(small)
    assert not [p for p in laptop.progress if p.stage == "evict_refused"]


# ── the three ways pressure reaches eviction ─────────────────────────────────

def test_the_pressure_chain_keeps_small_blobs_and_frees_the_big_ones(cluster_of):
    """check_capacity -> space_pressure_detected -> the evict_on_space_pressure policy."""
    with freeze_time(START) as clock:
        c, srv, laptop, hs = pool(cluster_of, clock, smallest=2 * KB, sizes=[1 * KB] * 4 + [3 * KB] * 3)
        squeeze(srv)
        srv.run("check_capacity")
        c.settle()
        tiny, big = hs[:4], hs[4:]
        assert all(srv.has_blob(h) for h in tiny)
        assert not any(srv.has_blob(h) for h in big)
        assert all(laptop.has_blob(h) for h in hs)


def test_the_sweep_keeps_small_blobs_and_exempt_ones_do_not_starve_the_rest(cluster_of):
    """The paced catch-up reads a bounded window of candidates (cap * 8) and tries `cap` of them: twenty exempt blobs
    at the head must neither be attempted nor fill that window."""
    with freeze_time(START) as clock:
        _c, srv, laptop, hs = pool(cluster_of, clock, smallest=2 * KB, sizes=[1 * KB] * 20 + [3 * KB] * 3)
        squeeze(srv)
        srv.env_store.max_dispatch_per_event = 1
        tiny, big = hs[:20], hs[20:]
        for _ in big:
            assert sweep(srv)["evicted"] == 1
        assert sweep(srv) == NOTHING                                # still over its watermark, nothing eligible: it ends
        assert all(srv.has_blob(h) for h in tiny) and not any(srv.has_blob(h) for h in big)
        assert all(laptop.has_blob(h) for h in hs)


def test_relief_that_cannot_be_reached_ends_instead_of_looping(cluster_of):
    """Over the watermark with only exempt blobs left: every reading and every sweep finds no candidate, so nothing is
    attempted, refused, retried or backed off — and the only thing the log gains is the readings themselves."""
    with freeze_time(START) as clock:
        c, srv, _laptop, hs = pool(cluster_of, clock, smallest=4 * KB, sizes=[3 * KB] * 3)
        squeeze(srv)                                                # 9KB of 10KB: past the 80% watermark
        events_before = len(srv.store)
        for _ in range(3):
            srv.run("check_capacity")
            c.settle()
            assert sweep(srv) == NOTHING
        assert srv.sweep_state == {}                                # no attempt, so no backoff memory to grow
        assert events_of(srv, "blob_evicted", by="srv") == []
        assert not [p for p in srv.progress if p.stage in ("evict_refused", "sweep_error")]
        assert len(events_of(srv, "space_pressure_detected", by="srv")) == 3
        assert len(srv.store) == events_before + 3                  # one reading, one fact; nothing else is generated
        assert all(srv.has_blob(h) for h in hs)


# ── the law ──────────────────────────────────────────────────────────────────

def test_the_invariant_flags_a_small_blob_evicted_under_pressure_and_nothing_else(cluster_of):
    with freeze_time(START) as clock:
        c, srv, _laptop, (small, big) = pool(cluster_of, clock, smallest=0, sizes=[500, 3000])
        run = SimpleNamespace(cluster=c)
        srv.run("evict_blob", blob_hash=small, reason="pressure")  # allowed: no exemption is configured yet
        assert invariants.small_blobs_stay_under_pressure(run) == []
        srv.env_store.min_evict_bytes = 1000                        # ... now the law says it should not have happened
        (violation,) = invariants.small_blobs_stay_under_pressure(run)
        assert small[:12] in violation and "500 bytes" in violation and "1000" in violation
        srv.run("evict_blob", blob_hash=big, reason="pressure")
        assert len(invariants.small_blobs_stay_under_pressure(run)) == 1       # a big one is no violation
        assert invariants.REGISTRY["small-blobs-stay"] is invariants.small_blobs_stay_under_pressure


def test_the_invariant_does_not_flag_a_drain(cluster_of):
    c = cluster_of(srv=HOT, laptop=ARCHIVE, nas=ARCHIVE)
    small = c.nodes["srv"].edge_put([b"s" * 100], "photos")
    for peer in ("laptop", "nas"):
        sync_both(c, "srv", peer)
    laptop = c.nodes["laptop"]
    laptop.env_store.min_evict_bytes = 10 ** 9
    laptop.announce(draining=True)
    sync_both(c, "laptop", "nas")
    laptop.run("evict_blob", blob_hash=small, reason="drain")
    assert events_of(laptop, "blob_evicted", by="laptop")[0]["reason"] == "drain"
    assert invariants.small_blobs_stay_under_pressure(SimpleNamespace(cluster=c)) == []
