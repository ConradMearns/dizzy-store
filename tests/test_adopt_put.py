"""adopt_collection and put_blob: what they record, and that repeating them is free."""
import pytest

from conftest import ARCHIVE, events_of, flip, sha, sync_both
from storeutil import blob_path


def tree(tmp_path, **files):
    root = tmp_path / "tree"
    root.mkdir(exist_ok=True)
    for name, data in files.items():
        (root / name).write_bytes(data)
    return root


def adopt(node, root, collection="books", layout="tree", **extra):
    node.run("adopt_collection", collection=collection, root=str(root), layout=layout, **extra)


def facts(node, kind):
    return events_of(node, kind, by=node.name) if kind == "blob_stored" else events_of(node, kind)


# ── adopt ────────────────────────────────────────────────────────────────────

def test_re_adopting_a_tree_records_nothing_new(cluster_of, tmp_path):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    root = tree(tmp_path, one=b"first", two=b"second")
    adopt(a, root)
    before = len(a.store)
    adopt(a, root)
    assert len(a.store) == before


def test_identical_files_in_one_tree_are_one_blob(cluster_of, tmp_path):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    adopt(a, tree(tmp_path, copy_one=b"same bytes", copy_two=b"same bytes"))
    assert len(facts(a, "blob_registered")) == 1
    assert len(facts(a, "blob_stored")) == 1


def test_bytes_the_cluster_already_knows_are_not_registered_again(cluster_of, tmp_path):
    c = cluster_of(a=ARCHIVE, b={"role": "archive", "wants": []})
    a, b = c.nodes["a"], c.nodes["b"]
    data = b"already in the cluster"
    a.edge_put([data], "photos")
    sync_both(c, "a", "b")
    adopt(b, tree(tmp_path, same=data), collection="books")
    registered = [e for e in facts(b, "blob_registered") if e["blob_hash"] == sha(data)]
    assert len(registered) == 1                                   # a's registration; b added none
    assert b.query("get_blob", blob_hash=sha(data)).collection == "photos"
    assert b.has_blob(sha(data))
    assert [e["source"] for e in facts(b, "blob_stored") if e["node_id"] == "b"] == ["adopted"]


def test_a_cas_tree_whose_name_lies_is_skipped_and_reported(cluster_of, tmp_path):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    good, liar = b"honest bytes", b"the real content"
    root = tmp_path / "cas"
    for name, data in ((sha(good), good), (sha(b"claimed"), liar)):
        path = root / name[:2] / name[2:4] / name
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
    adopt(a, root, layout="cas")
    assert [e["blob_hash"] for e in facts(a, "blob_registered")] == [sha(good)]
    assert any("skipped" in p.detail and sha(b"claimed")[:12] in p.detail for p in a.progress)


def test_link_adoption_costs_no_extra_space_and_a_copy_does(cluster_of, tmp_path):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    root = tree(tmp_path, linked=b"L" * 500, copied=b"C" * 500)
    adopt(a, root, collection="x", link=True)
    import os
    assert os.path.samefile(root / "linked", blob_path(a.root, sha(b"L" * 500)))
    (root / "linked").unlink()
    (root / "linked").write_bytes(b"L" * 500)
    # a second tree adopted by default (a copy): its files are independent of the originals
    other = tmp_path / "other"
    other.mkdir()
    (other / "copied").write_bytes(b"C" * 500)
    adopt(a, other, collection="y")
    assert not os.path.samefile(other / "copied", blob_path(a.root, sha(b"C" * 500)))


# ── put ──────────────────────────────────────────────────────────────────────

def place(node, data):
    """Bytes the edge has already written under the node's root (what put_blob expects)."""
    h = sha(data)
    path = blob_path(node.root, h)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return h


def test_put_refuses_a_declared_size_that_is_not_the_files(cluster_of):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    h = place(a, b"x" * 100)
    before = len(a.store)
    with pytest.raises(ValueError):
        a.run("put_blob", blob_hash=h, byte_size=99, collection="photos")
    assert len(a.store) == before


def test_put_refuses_an_unusable_recipe_even_when_the_bytes_are_there(cluster_of):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    h = place(a, b"x" * 100)
    before = len(a.store)
    with pytest.raises(ValueError):
        a.run("put_blob", blob_hash=h, byte_size=100, collection="photos",
              chunk_size=10, chunk_hashes=[sha(b"1")] * 2)           # ten chunks needed
    assert len(a.store) == before


def test_putting_the_same_blob_twice_records_nothing_the_second_time(cluster_of):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    h = place(a, b"x" * 100)
    a.run("put_blob", blob_hash=h, byte_size=100, collection="photos")
    before = len(a.store)
    a.run("put_blob", blob_hash=h, byte_size=100, collection="photos")
    assert len(a.store) == before


# ── adopting the directory the store itself lives in ─────────────────────────

def test_a_cas_tree_that_is_the_stores_own_root_is_adopted_in_place(cluster_of):
    """The logger's cas/ has the store's layout, so the store can manage it where it
    stands: files already at their addresses are hashed and recorded, never copied or
    linked — which is what lets evicting a blob really free its disk space."""
    import os
    a = cluster_of(a=ARCHIVE).nodes["a"]
    blobs = {}
    for data in (b"first photo" * 50, b"second video" * 80, b"third" * 10):
        h = sha(data)
        path = blob_path(a.root, h)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        blobs[h] = (path, os.stat(path).st_ino)
    adopt(a, a.root, collection="media", layout="cas")
    assert {e["blob_hash"] for e in facts(a, "blob_registered")} == set(blobs)
    for h, (path, inode) in blobs.items():
        assert a.has_blob(h)
        assert os.stat(path).st_ino == inode and os.stat(path).st_nlink == 1   # untouched: no copy, no link
    before = len(a.store)
    adopt(a, a.root, collection="media", layout="cas")           # and a re-run reads nothing, records nothing
    assert len(a.store) == before
