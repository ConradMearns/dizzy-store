"""Principle 3 as unit tests: each projection that more than one device can write to
folds the same events to the same row, whatever order they arrive in."""
import itertools
from datetime import datetime, timedelta, timezone

import pytest

from conftest import sha
from dizzy_store.sim import SimCluster
from gen_def.pydantic.events import (BlobAccessRecorded, BlobRegistered, BlobStored,
                                     CollectionPolicySet, NodeAnnounced, ScrubCompleted)
from gen_def.sqla.models.pool import ScrubState
from storeutil import scrub_id

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
H = sha(b"blob")


def at(**delta) -> datetime:
    return T0 + timedelta(**delta)


def fold(tmp_path, label, events):
    """A brand-new device whose read models are the fold of ``events``, in that order."""
    node = SimCluster(tmp_path / label).add_node("n")
    for event in events:
        for _name, runner in node.runners.get(type(event), []):
            runner(event, T0)
    node.session.commit()
    return node


def every_order(tmp_path, events, read):
    """The value ``read(node)`` returns after folding every permutation of ``events``."""
    return [read(fold(tmp_path, f"p{i}", list(order)))
            for i, order in enumerate(itertools.permutations(events))]


def registered(when, collection="photos", recipe=None):
    chunk_size, hashes = recipe or (None, None)
    return BlobRegistered(blob_hash=H, byte_size=4096, collection=collection, chunk_size=chunk_size,
                          chunk_hashes=hashes, occurred_at=when)


def test_the_catalog_keeps_the_earliest_registration_in_any_order(tmp_path):
    events = [registered(at(minutes=2), "docs"), registered(at(minutes=1), "photos"),
              registered(at(minutes=3), "books")]
    seen = every_order(tmp_path, events, lambda n: n.query("get_blob", blob_hash=H).collection)
    assert set(seen) == {"photos"}


def test_a_later_registration_with_a_recipe_fills_in_the_one_without(tmp_path):
    hashes = [sha(bytes([i])) for i in range(4)]
    events = [registered(at(minutes=1)), registered(at(minutes=2), recipe=(1024, hashes))]
    seen = every_order(tmp_path, events, lambda n: (n.query("get_blob", blob_hash=H).chunk_size,
                                                    tuple(n.query("get_blob", blob_hash=H).chunk_hashes or ())))
    assert set(seen) == {(1024, tuple(hashes))}


def test_the_earliest_recipe_wins_in_any_order(tmp_path):
    first, second = [sha(b"1")] * 4, [sha(b"2")] * 4
    events = [registered(at(minutes=2), recipe=(1024, second)), registered(at(minutes=1), recipe=(1024, first))]
    seen = every_order(tmp_path, events, lambda n: tuple(n.query("get_blob", blob_hash=H).chunk_hashes))
    assert set(seen) == {tuple(first)}


def scrubbed(started, completed, node="n", epoch="n-1"):
    return ScrubCompleted(node_id=node, epoch=epoch, collection="docs", checked=1, corrupt=0, bytes_checked=1,
                          cursor=None, pass_complete=True, pass_started_at=started, occurred_at=completed)


def test_the_latest_pass_start_wins_in_any_order(tmp_path):
    events = [scrubbed(at(days=1), at(days=2)), scrubbed(at(days=20), at(days=40)),
              scrubbed(at(days=5), at(days=6))]
    seen = every_order(tmp_path, events, lambda n: n.session.get(
        ScrubState, scrub_id("n", "n-1", "docs")).last_full_pass_at)
    assert set(seen) == {at(days=20).replace(tzinfo=None)}      # the start of the latest pass, not its end


def announced(when, **card):
    fields = dict(node_id="x", cluster_id="c", epoch="x-1", role="archive", site="home", location_note=None,
                  endpoints=[], wants=["*"], draining=False)
    return NodeAnnounced(**{**fields, **card}, occurred_at=when)


def test_announcements_at_the_same_instant_resolve_alike_in_any_order(tmp_path):
    events = [announced(T0, role="archive"), announced(T0, role="cold"), announced(T0, draining=True)]
    seen = every_order(tmp_path, events, lambda n: (n.query("get_node_profile", node_id="x").role,
                                                    n.query("get_node_profile", node_id="x").draining))
    assert len(set(seen)) == 1


def test_a_later_announcement_beats_an_earlier_one_in_any_order(tmp_path):
    events = [announced(at(minutes=1), role="archive"), announced(at(minutes=5), role="cold"),
              announced(at(minutes=3), role="hot")]
    seen = every_order(tmp_path, events, lambda n: n.query("get_node_profile", node_id="x").role)
    assert set(seen) == {"cold"}


def test_policies_at_the_same_instant_resolve_alike_in_any_order(tmp_path):
    events = [CollectionPolicySet(collection="photos", min_sites=n, verify_max_age_days=30, evictable=True,
                                  occurred_at=T0) for n in (2, 3, 4)]
    seen = every_order(tmp_path, events, lambda n: n.query("get_collection_policy", collection="photos").min_sites)
    assert len(set(seen)) == 1


def test_the_latest_read_wins_in_any_order(tmp_path):
    held = [announced(T0, node_id="n", epoch="n-1"), registered(T0),
            BlobStored(node_id="n", epoch="n-1", blob_hash=H, source="upload", occurred_at=T0)]
    reads = [BlobAccessRecorded(node_id="n", epoch="n-1", blob_hashes=[H], last_access_ats=[at(hours=h)],
                                occurred_at=at(hours=h)) for h in (3, 1, 2)]    # the blob must exist first
    seen = []
    for i, order in enumerate(itertools.permutations(reads)):
        node = fold(tmp_path, f"r{i}", held + list(order))
        seen.append(node.query("get_blob_replicas", blob_hash=H).last_access_ats)
    assert all(len(ats) == 1 for ats in seen)
    assert {ats[0] for ats in seen} == {"2026-01-01T03:00:00"}                 # the latest read, in every order
