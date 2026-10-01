"""scrub_blobs: what it does with what it finds."""
from conftest import ARCHIVE, events_of, flip
from storeutil import blob_path


def test_scrub_quarantines_what_it_finds_and_keeps_the_evidence(cluster_of):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    good = a.edge_put([b"g" * 400], "docs")
    bad = a.edge_put([b"b" * 400], "docs")
    path = blob_path(a.root, bad)
    flip(path)
    rotted = path.read_bytes()
    a.run("scrub_blobs", max_bytes=1 << 20)
    kept = a.root / ".store" / "quarantine" / bad
    assert kept.read_bytes() == rotted                       # the damaged bytes are kept for inspection
    assert not path.exists()                                 # and no longer sit at a verified address
    assert a.has_blob(good)
    corrupt = events_of(a, "blob_corrupt")
    assert [(e["blob_hash"], e["found_hash"] is not None) for e in corrupt] == [(bad, True)]
    done = events_of(a, "scrub_completed")[-1]
    assert (done["checked"], done["corrupt"], done["pass_complete"]) == (2, 1, True)
