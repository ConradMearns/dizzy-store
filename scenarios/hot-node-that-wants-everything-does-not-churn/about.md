A hot node whose card wants a collection in full never evicts it for space.
tags: eviction, pressure, wants, churn, principle-7, found-by-independent-review
Without the exclusion a node that wanted everything and had a limit fetched, evicted and
fetched the same blobs on every sweep (3 sweeps -> 6 stores, 6 evictions).
