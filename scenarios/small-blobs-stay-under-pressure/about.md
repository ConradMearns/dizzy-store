Pressure never takes a blob smaller than min_evict_bytes — not even the oldest — and frees the next-oldest big ones instead.
tags: eviction, pressure, min-evict-bytes, principle-11
The server holds four tiny blobs (the oldest) and three big ones, 13KB against a 10KB limit. Plain least-recently-touched-
first would drop the tiny ones; with `min_evict_bytes: 2KB` they are not candidates at all, so the three big ones go — all
of them, because the tiny ones do not count toward what has to be freed — and every byte is still on the laptop.
