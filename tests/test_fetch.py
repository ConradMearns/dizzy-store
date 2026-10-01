"""replicate_blob and evict_blob beyond the happy path: what a failure records, whom a
fetch asks first, that an interrupted chunked fetch resumes, and what an eviction
writes down about the proof it relied on."""
import importlib
import os
from types import SimpleNamespace

import pytest

from conftest import ARCHIVE, COLD, HOT, IDLE, events_of, flip, sha, sync_both
from storeutil import PeerUnreachable, Throttle, blob_path


class SpyPeers:
    """Wraps a node's real peers client; records every ``read_blob`` it makes and can
    drop the link after N of them."""

    def __init__(self, inner, drop_after=None):
        self.inner, self.reads, self.drop_after = inner, [], drop_after

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def read_blob(self, peer_id, blob_hash, offset=0, length=None):
        if self.drop_after is not None and len(self.reads) >= self.drop_after:
            raise PeerUnreachable(f"{peer_id} went away")
        self.reads.append((peer_id, offset))
        return self.inner.read_blob(peer_id, blob_hash, offset, length)


def uploaded(cluster, name="a", data=b"x" * 3000, collection="photos", chunk_size=None):
    """A blob uploaded at ``name`` and known to every device (nobody fetched it)."""
    node = cluster.nodes[name]
    h = node.edge_put([data], collection, chunk_size=chunk_size)
    for other in cluster.nodes:
        if other != name:
            sync_both(cluster, name, other)
    return h


# ── what a failed fetch records ──────────────────────────────────────────────

def test_a_source_that_sends_bad_bytes_is_named_in_the_failure(cluster_of):
    c = cluster_of(a=ARCHIVE, b=IDLE)
    h = uploaded(c)
    flip(blob_path(c.nodes["a"].root, h))                    # rotted: same size, wrong bytes
    b = c.nodes["b"]
    b.run("replicate_blob", blob_hash=h, from_node="a", reason="backfill")
    failures = events_of(b, "blob_replication_failed")
    assert [(f["reason"], f["from_node"]) for f in failures] == [("hash_mismatch", "a")]
    assert not b.has_blob(h)


def test_a_peer_that_lacks_the_bytes_is_recorded_not_tried(cluster_of):
    c = cluster_of(a=ARCHIVE, b=IDLE)
    h = uploaded(c)
    blob_path(c.nodes["a"].root, h).unlink()                 # its log still says it holds it
    b = c.nodes["b"]
    b.run("replicate_blob", blob_hash=h, from_node="a", reason="backfill")   # does not raise
    failures = events_of(b, "blob_replication_failed")
    assert [(f["reason"], f["from_node"]) for f in failures] == [("not_held", "a")]


def test_an_unregistered_blob_is_not_held_by_anyone(cluster_of):
    c = cluster_of(a=ARCHIVE)
    c.nodes["a"].run("replicate_blob", blob_hash="e" * 64, reason="backfill")
    assert [f["reason"] for f in events_of(c.nodes["a"], "blob_replication_failed")] == ["not_held"]


# ── whom a fetch asks, and what it writes down ───────────────────────────────

def test_archives_are_asked_before_hot_nodes_and_cold_drives(cluster_of):
    c = cluster_of(srv=HOT, drive=COLD, laptop=ARCHIVE, fresh=IDLE)
    h = uploaded(c, name="srv")
    for node in ("drive", "laptop"):
        c.nodes[node].run("replicate_blob", blob_hash=h, from_node="srv", reason="backfill")
    sync_both(c, "laptop", "fresh")
    sync_both(c, "drive", "fresh")
    fresh = c.nodes["fresh"]
    spy = fresh.peers = SpyPeers(fresh.peers)
    fresh.run("replicate_blob", blob_hash=h, reason="backfill")          # no hint
    assert spy.reads[0][0] == "laptop"                                    # not the drive, not the server


def test_the_stored_fact_says_why_the_blob_was_fetched(cluster_of):
    c = cluster_of(a=ARCHIVE, b=IDLE)
    h = uploaded(c)
    c.nodes["b"].run("replicate_blob", blob_hash=h, from_node="a", reason="read_through")
    assert [e["source"] for e in events_of(c.nodes["b"], "blob_stored", by="b")] == ["read_through"]


# ── chunked fetches: resumable, and verified end to end ──────────────────────

def test_an_interrupted_chunked_fetch_resumes_from_its_verified_chunks(cluster_of):
    c = cluster_of(a=ARCHIVE, b=IDLE)
    h = uploaded(c, data=os.urandom(4000), collection="video", chunk_size=1000)   # four chunks
    b = c.nodes["b"]
    spy = b.peers = SpyPeers(b.peers, drop_after=2)          # the link dies on the third chunk
    b.run("replicate_blob", blob_hash=h, from_node="a", reason="backfill")
    staging = b.root / ".store" / "tmp" / f"{h}.chunks"
    assert sorted(p.name for p in staging.iterdir()) == ["000000", "000001"]      # two verified chunks kept
    assert not b.has_blob(h)
    assert not events_of(b, "blob_stored", by="b")           # one fact, when the whole file is assembled

    spy.drop_after, spy.reads = None, []
    b.run("replicate_blob", blob_hash=h, from_node="a", reason="backfill")
    assert [offset for _peer, offset in spy.reads] == [2000, 3000]                # only what was missing
    assert b.has_blob(h)
    assert len(events_of(b, "blob_stored", by="b")) == 1
    assert not staging.exists()


def test_chunks_that_each_verify_but_assemble_to_the_wrong_file_are_refused(tmp_path):
    """The recipe describes some OTHER file than the one this hash names."""
    module = importlib.import_module("replicate_blob")
    data = os.urandom(3000)
    pieces = [data[i:i + 1000] for i in range(0, 3000, 1000)]
    blob = SimpleNamespace(blob_hash="f" * 64, byte_size=3000, chunk_size=1000,
                           chunk_hashes=[sha(p) for p in pieces])
    peers = SimpleNamespace(read_blob=lambda peer, h, offset=0, length=None: iter([data[offset:offset + length]]))
    quiet = SimpleNamespace(transfer_progress=lambda *_: None, peer_health=lambda *_: None)
    context = SimpleNamespace(env=SimpleNamespace(peers=peers), telemetry=quiet)
    part = tmp_path / "part"
    outcome = module._fetch_chunked(context, blob, ["p"], part, tmp_path / "staging", Throttle(0))
    assert outcome[0] == "mismatch"
    assert not part.exists()


# ── an eviction writes down the proof it relied on ───────────────────────────

def test_an_eviction_records_how_many_sites_it_proved(cluster_of):
    c = cluster_of(server=HOT, laptop=ARCHIVE, cabin=ARCHIVE)
    server = c.nodes["server"]
    server.run("set_collection_policy", collection="photos", min_sites=2,
               verify_max_age_days=30, evictable=True)
    h = uploaded(c, name="server")
    for node in ("laptop", "cabin"):
        sync_both(c, "server", node)
    c.settle()
    server.run("evict_blob", blob_hash=h, reason="pressure")
    assert not server.has_blob(h)
    evicted = events_of(server, "blob_evicted", by="server")
    assert [e["confirmed_sites"] for e in evicted] == [2]
    assert [e["reason"] for e in evicted] == ["pressure"]


def test_a_command_that_names_the_node_updates_the_card_peers_are_told(cluster_of):
    """verify_blob answers from the live card; an announce_node issued through the
    admin API / CLI (not through Node.announce) must move it too."""
    c = cluster_of(a=ARCHIVE)
    a = c.nodes["a"]
    h = a.edge_put([b"y" * 100], "photos")
    assert a.surface.verify_blob(h)["draining"] is False
    a.run("announce_node", role="archive", site="a", draining=True, wants=["*"], endpoints=[])
    assert a.card["draining"] is True
    assert a.surface.verify_blob(h) == {"held": True, "size": 100, "role": "archive", "draining": True}
