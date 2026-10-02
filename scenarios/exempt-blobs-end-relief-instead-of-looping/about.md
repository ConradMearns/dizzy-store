When everything left is exempt, relief is unreachable — it ends there; nothing is evicted and nothing is retried.
tags: eviction, pressure, min-evict-bytes, principle-9, principle-11
Every blob on the server is under min_evict_bytes while it sits over its watermark. Repeated pressure readings and sweeps
find no candidates, so there is nothing to attempt, refuse or back off from; the bytes all stay put.
