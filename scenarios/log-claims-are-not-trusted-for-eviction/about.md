A reachable peer whose bytes are gone must not be counted as a copy.
tags: eviction, safety, principle-7, found-by-mutation-testing
The log says "present"; only a live has+size check tells the truth. Without the
live check this scenario destroys the last copy (and the never-last-copy
invariant would say so). Added after a mutation of evict_blob survived the first
batch — the offline scenario was guarded by the unreachable path, not this one.
