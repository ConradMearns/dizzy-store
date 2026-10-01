"""What happens when a device dies, or a step fails, halfway through its work.

The log is the truth and the read models are a fold of it, so the contract is:
whatever was appended is never lost, and a fold that did not finish is redone
from the log on the next start. Also: a full disk is a recorded fact, not a crash.
"""
import errno
import hashlib
import importlib
import os

import pytest

from conftest import rebuilt, reopen
import dizzy_store.node as node_mod
from dizzy_store.invariants import _snapshot
from dizzy_store.node import DIRTY
from dizzy_store.sim import SimCluster
from storeutil import get_flag

HOT = {"role": "hot", "site": "hetzner", "wants": []}
ARCHIVE = {"role": "archive", "site": "home", "wants": ["*"]}


def pair(tmp_path, b_wants=("*",)):
    cluster = SimCluster(tmp_path)
    a = cluster.found("a", ARCHIVE)
    b = cluster.add_node("b", {"role": "archive", "site": "attic", "wants": list(b_wants)})
    for node in cluster.nodes.values():
        node.announce()
    cluster.settle()
    return cluster, a, b


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── a fold that dies after the events landed ─────────────────────────────────

def test_a_crash_between_append_and_fold_heals_on_restart(tmp_path, monkeypatch):
    cluster, a, b = pair(tmp_path)
    blobs = [a.edge_put([bytes([i]) * 300], "photos") for i in range(1, 6)]
    cluster.partitions = [{"a"}, {"b"}]                  # b cannot hear the uploads yet…
    cluster.settle()
    cluster.partitions = []
    before = len(b.store)

    real = node_mod.fold_envelopes

    def power_cut(added, *_a, **_k):
        raise RuntimeError("power cut mid-fold")
    monkeypatch.setattr(node_mod, "fold_envelopes", power_cut)
    with pytest.raises(RuntimeError):
        b.run("sync_peer", peer_id="a", direction="pull")
    monkeypatch.setattr(node_mod, "fold_envelopes", real)

    assert len(b.store) > before                         # the events are in the log…
    assert not b.query("get_blob", blob_hash=blobs[0]).found   # …and the read models never saw them
    assert get_flag(b.session, DIRTY) == "1"             # and the node knows it

    b2 = reopen(cluster, b)                              # the restart
    assert rebuilt(b2)
    assert all(b2.query("get_blob", blob_hash=h).found for h in blobs)
    assert get_flag(b2.session, DIRTY) == "0"
    assert not rebuilt(reopen(cluster, b2))              # healed once, then left alone


def test_a_clean_run_never_triggers_a_rebuild(tmp_path):
    cluster, a, b = pair(tmp_path)
    a.edge_put([b"x" * 500], "photos")
    cluster.settle()
    assert get_flag(b.session, DIRTY) == "0"
    assert not rebuilt(reopen(cluster, b))


def test_rebuilding_gives_back_exactly_the_same_models(tmp_path):
    cluster, a, b = pair(tmp_path)
    for i in range(1, 4):
        a.edge_put([bytes([i]) * 200], "photos")
    cluster.settle()
    b.run("scrub_blobs", max_bytes=1 << 20)
    cluster.settle()
    for node in (a, b):
        before = _snapshot(node)
        node.rebuild()
        assert _snapshot(node) == before, f"{node.name}: the fold is not a function of the log"


# ── a step that fails after doing real work ──────────────────────────────────

def test_events_emitted_before_a_failure_are_recorded_not_stranded(tmp_path):
    """adopt emits for a.txt, then cannot read b.txt. The first file's facts are real
    (its bytes are in the store) and must reach the log now, not whenever some
    unrelated command next happens to drain the engine's queue."""
    cluster, a, _b = pair(tmp_path)
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_bytes(b"first file")
    (tree / "b.txt").write_bytes(b"second file")
    os.chmod(tree / "b.txt", 0)
    try:
        with pytest.raises(PermissionError):
            a.run("adopt_collection", collection="books", root=str(tree), layout="tree")
    finally:
        os.chmod(tree / "b.txt", 0o644)
    h = sha(b"first file")
    assert a.query("get_blob", blob_hash=h).found
    assert a.has_blob(h)
    a2 = reopen(cluster, a)                              # and a restart agrees
    assert a2.query("get_blob", blob_hash=h).found and a2.has_blob(h)


# ── a full disk is a fact, not a crash ───────────────────────────────────────

def test_running_out_of_disk_mid_fetch_is_recorded_and_clean(tmp_path, monkeypatch):
    cluster, a, b = pair(tmp_path, b_wants=())           # b wants nothing: it fetches only when told
    h = a.edge_put([b"payload" * 400], "photos")
    a.run("sync_peer", peer_id="b", direction="both")    # b hears of the blob (and, wanting nothing, leaves it)
    cluster.settle()
    assert b.query("get_blob", blob_hash=h).found and not b.has_blob(h)
    module = importlib.import_module("replicate_blob")
    real_open = open

    def full_disk(path, mode="r", *args, **kwargs):
        if "w" in mode and str(path).endswith(".part"):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(module, "open", full_disk, raising=False)

    b.run("replicate_blob", blob_hash=h, from_node="a", reason="backfill")   # does not raise
    failures = [e.payload for e in b.store.iterate() if e.type == "blob_replication_failed"]
    assert [f["reason"] for f in failures] == ["out_of_space"]
    assert not b.has_blob(h)
    assert not list((b.root / ".store" / "tmp").glob("*.part"))

    monkeypatch.undo()                                   # space comes back; the next try succeeds
    b.run("replicate_blob", blob_hash=h, from_node="a", reason="backfill")
    assert b.has_blob(h)


# ── the read models carry what placement questions join by ───────────────────

def test_the_read_models_carry_the_indexes_placement_questions_need(tmp_path):
    """The generated models declare primary keys only, so without these a per-blob
    lookup scans the whole location table: measured at 280 s per call over 30k blobs."""
    from sqlalchemy import text
    node = SimCluster(tmp_path).add_node("n")

    def indexes(table):
        return {row[1] for row in node.session.execute(text(f"PRAGMA index_list('{table}')"))}
    assert {"ix_location_blob", "ix_location_node"} <= indexes("BlobLocation")
    assert "ix_blob_collection" in indexes("Blob")
