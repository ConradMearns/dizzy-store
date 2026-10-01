"""The shared helpers whose mistakes cost data: the path guard, verified placement,
the chunk-recipe check, and the freshness window."""
import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest

import dizzy_store  # noqa: F401 — puts the element libraries (storeutil) on sys.path
from storeutil import (Policy, blob_path, copy_is_fresh, ensure_blob_file, is_hash,
                       sha256_file, strictly_after, valid_recipe)

H = "ab" + "cd" + "0" * 60


# ── a hash must look like one before it becomes a path ───────────────────────

@pytest.mark.parametrize("bad", [
    "", "/etc/hostname", "../../etc/passwd", "a" * 63, "a" * 65, "g" * 64,
    "A" * 64, ("ab" * 31) + "/x", H + "\n", None, 12,
])
def test_blob_path_refuses_anything_that_is_not_a_sha256(bad):
    with pytest.raises(ValueError):
        blob_path("/root", bad)
    assert not is_hash(bad)


def test_blob_path_shards_two_levels():
    assert blob_path("/r", H).as_posix() == f"/r/ab/cd/{H}"


# ── verified placement: copy by default, link on request, never trust a stray ─

def _src(tmp_path, data=b"hello world" * 100):
    src = tmp_path / "orig.bin"
    src.write_bytes(data)
    (tmp_path / "root" / ".store").mkdir(parents=True, exist_ok=True)   # a store always has its state dir
    return src, hashlib.sha256(data).hexdigest()


def test_default_adoption_copies_and_leaves_the_original_alone(tmp_path):
    src, h = _src(tmp_path)
    dest = blob_path(tmp_path / "root", h)
    assert ensure_blob_file(src, dest, h, tmp_path / "tmp") is True
    assert sha256_file(dest) == h
    assert not os.path.samefile(src, dest)               # its own bytes: edits to src do not reach it
    src.write_bytes(b"edited in place")
    assert sha256_file(dest) == h
    assert ensure_blob_file(src, dest, h, tmp_path / "tmp") is False   # already there and right


def test_link_adoption_shares_the_bytes(tmp_path):
    src, h = _src(tmp_path)
    dest = blob_path(tmp_path / "root", h)
    assert ensure_blob_file(src, dest, h, tmp_path / "tmp", link=True) is True
    assert os.path.samefile(src, dest)
    assert not list((tmp_path / "tmp").glob("*.part"))


def test_link_falls_back_to_a_copy_across_filesystems(tmp_path, monkeypatch):
    src, h = _src(tmp_path)
    dest = blob_path(tmp_path / "root", h)

    def refuse(*_a, **_k):
        raise OSError(18, "Invalid cross-device link")
    monkeypatch.setattr(os, "link", refuse)
    assert ensure_blob_file(src, dest, h, tmp_path / "tmp", link=True) is True
    assert sha256_file(dest) == h
    assert not os.path.samefile(src, dest)


def test_a_stray_file_at_the_address_is_replaced_not_believed(tmp_path):
    src, h = _src(tmp_path)
    dest = blob_path(tmp_path / "root", h)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(src.read_bytes()[:50])              # half a file squatting at the address
    assert ensure_blob_file(src, dest, h, tmp_path / "tmp") is True
    assert sha256_file(dest) == h


def test_adopting_in_place_is_a_no_op(tmp_path):
    src, h = _src(tmp_path)
    dest = blob_path(tmp_path / "root", h)
    dest.parent.mkdir(parents=True)
    os.link(src, dest)
    assert ensure_blob_file(src, dest, h, tmp_path / "tmp") is False


def test_bytes_that_do_not_match_the_claimed_hash_never_land(tmp_path):
    src, _h = _src(tmp_path)
    wrong = "f" * 64
    dest = blob_path(tmp_path / "root", wrong)
    with pytest.raises(ValueError):
        ensure_blob_file(src, dest, wrong, tmp_path / "tmp")
    assert not dest.exists()
    assert not list((tmp_path / "tmp").glob("*.part"))


# ── chunk recipes ────────────────────────────────────────────────────────────

def _hashes(n):
    return [("%064x" % (i + 1)) for i in range(n)]


@pytest.mark.parametrize("size, chunk, hashes, ok", [
    (4096, 1024, _hashes(4), True),
    (4097, 1024, _hashes(5), True),                       # a short last chunk
    (4096, 1024, _hashes(3), False),                      # too few
    (4096, 1024, _hashes(5), False),                      # too many
    (4096, 0, _hashes(4), False),                         # zero chunk size
    (4096, None, _hashes(4), False),                      # no chunk size
    (4096, -5, _hashes(4), False),
    (0, 1024, _hashes(1), False),                         # empty file has no chunks
    (4096, 1024, _hashes(3) + ["not-a-hash"], False),     # junk hash
    (4096, None, None, True),                             # no recipe at all
    (4096, None, [], True),
    (4096, 1024, [], False),                              # a chunk size with no hashes
])
def test_valid_recipe(size, chunk, hashes, ok):
    assert valid_recipe(size, chunk, hashes) is ok


# ── freshness ────────────────────────────────────────────────────────────────

NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)


def test_a_copy_is_fresh_up_to_exactly_the_window():
    policy = Policy(min_sites=2, verify_max_age_days=30)
    edge = NOW - timedelta(days=30)
    assert copy_is_fresh(edge, policy, NOW)
    assert not copy_is_fresh(edge - timedelta(microseconds=1), policy, NOW)
    assert not copy_is_fresh(None, policy, NOW)
    assert copy_is_fresh(edge.isoformat(), policy, NOW)   # as a column or as the wire's string
    assert copy_is_fresh(edge.replace(tzinfo=None), policy, NOW)


# ── a device's later word beats its earlier one ──────────────────────────────

def test_strictly_after_never_lets_a_later_fact_lose_to_an_earlier_one():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert strictly_after(t, None) == t
    assert strictly_after(t + timedelta(seconds=1), t) == t + timedelta(seconds=1)
    assert strictly_after(t, t) == t + timedelta(microseconds=1)                    # same instant
    assert strictly_after(t - timedelta(days=9), t) == t + timedelta(microseconds=1)  # clock went back
    assert strictly_after(t, t.isoformat()) == t + timedelta(microseconds=1)
    assert strictly_after(t, t.replace(tzinfo=None)) == t + timedelta(microseconds=1)
    assert strictly_after(t, t).tzinfo is not None          # one wire format: always UTC-aware
