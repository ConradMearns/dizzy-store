"""An update must never leave a read model stale: change the code or schema that folds the log and the
next start rebuilds from the log."""
import sqlite3

import pytest

import dizzy_store.node as node_mod
from conftest import ARCHIVE, rebuilt, reopen, sha
from dizzy_store import fingerprint
from dizzy_store.invariants import _snapshot
from dizzy_store.node import FINGERPRINT, DIRTY
from storeutil import get_flag, set_flag


def populated(cluster_of):
    c = cluster_of(a=ARCHIVE)
    a = c.nodes["a"]
    hashes = [a.edge_put([bytes([i]) * 400], "photos") for i in range(1, 4)]
    return c, a, hashes


# ── the fingerprint ──────────────────────────────────────────────────────────

def test_the_fingerprint_is_stable_and_reads_the_things_a_fold_depends_on():
    first = fingerprint.readmodel_fingerprint()
    assert first == fingerprint.readmodel_fingerprint() and len(first) == 64
    names = {p.name for p in fingerprint.readmodel_files()}
    assert {"pool.py", "events.py", "storeutil.py", "blob_catalog_store.py", "scrub_state_store.py"} <= names


def test_any_change_to_those_files_changes_it(tmp_path, monkeypatch):
    f = tmp_path / "projection.py"
    f.write_text("def fold(): return 1\n")
    monkeypatch.setattr(fingerprint, "readmodel_files", lambda: [f])
    before = fingerprint.readmodel_fingerprint()
    f.write_text("def fold(): return 2\n")
    assert fingerprint.readmodel_fingerprint() != before


# ── what a node does about it ────────────────────────────────────────────────

def test_a_new_store_is_stamped_without_a_rebuild(cluster_of):
    c, a, _ = populated(cluster_of)
    assert not rebuilt(a)
    assert get_flag(a.session, FINGERPRINT) == fingerprint.readmodel_fingerprint()


def test_a_restart_of_unchanged_code_does_not_rebuild(cluster_of):
    c, a, _ = populated(cluster_of)
    assert not rebuilt(reopen(c, a))


def test_new_code_rebuilds_the_models_from_the_log_and_nothing_is_lost(cluster_of, monkeypatch):
    c, a, hashes = populated(cluster_of)
    before = _snapshot(a)
    a.close()
    monkeypatch.setattr(node_mod, "readmodel_fingerprint", lambda: "after-the-update")
    fresh = reopen(c, a)
    assert rebuilt(fresh)
    assert any("the code or schema changed" in p.detail for p in fresh.progress if p.stage == "rebuild")
    assert _snapshot(fresh) == before
    assert all(fresh.has_blob(h) for h in hashes)
    assert get_flag(fresh.session, FINGERPRINT) == "after-the-update"
    assert not rebuilt(reopen(c, fresh))                       # and then it is left alone


def test_a_schema_that_changed_shape_is_replaced_not_patched(cluster_of):
    """The old code's tables are in the wrong shape; the models are DERIVED, so drop them and fold again."""
    c, a, hashes = populated(cluster_of)
    before = _snapshot(a)
    db = a.root / ".store" / "models.db"
    a.close()
    raw = sqlite3.connect(db)
    raw.execute("DROP TABLE Blob")
    raw.execute("CREATE TABLE Blob (blob_hash TEXT PRIMARY KEY)")           # the old, narrower shape
    raw.execute("UPDATE StoreState SET value = 'built-by-an-older-version' WHERE key = ?", (FINGERPRINT,))
    raw.commit()
    raw.close()
    fresh = reopen(c, a)
    assert rebuilt(fresh)
    assert _snapshot(fresh) == before
    assert fresh.query("get_blob", blob_hash=hashes[0]).collection == "photos"


def test_a_database_from_before_fingerprints_is_rebuilt_once(cluster_of):
    c, a, hashes = populated(cluster_of)
    db = a.root / ".store" / "models.db"
    a.close()
    raw = sqlite3.connect(db)
    raw.execute("DELETE FROM StoreState WHERE key = ?", (FINGERPRINT,))
    raw.commit()
    raw.close()
    fresh = reopen(c, a)
    assert rebuilt(fresh) and all(fresh.has_blob(h) for h in hashes)
    assert not rebuilt(reopen(c, fresh))


def test_a_crash_marker_and_an_update_together_cost_one_rebuild(cluster_of, monkeypatch):
    c, a, hashes = populated(cluster_of)
    set_flag(a.session, DIRTY, "1")
    a.close()
    monkeypatch.setattr(node_mod, "readmodel_fingerprint", lambda: "after-the-update")
    fresh = reopen(c, a)
    assert [p.stage for p in fresh.progress].count("rebuild") == 1
    assert get_flag(fresh.session, DIRTY) == "0"
