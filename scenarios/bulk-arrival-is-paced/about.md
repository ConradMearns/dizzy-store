A merge that delivers a fresh backlog is still a bulk: reaction is bounded per merge.
tags: pacing, sweep, principle-9, found-by-independent-review
max_dispatch_per_event bounded reactions per EVENT, not per merge: adopting 150 files on
one device and syncing a laptop ran all 150 fetches inside one sync. The merge now reacts
to at most that many events of each type; the paced sweep takes it from there.
