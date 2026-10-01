A chunk recipe that could never be used is ignored, not trusted and not fatal.
tags: chunking, validation, robustness, found-by-independent-review
chunk_hashes with a missing or zero chunk_size was stored first-wins, replicate_blob then
raised a TypeError, and the sweep had no per-item guard — so every tick died on it.
