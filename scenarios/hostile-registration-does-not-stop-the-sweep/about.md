One poisoned item must not end a sweep tick: it is reported and skipped.
tags: sweep, robustness, backoff, found-by-independent-review
The sweep had no per-item guard, so a single blob that raised (an unusable chunk recipe, a
path-shaped hash from a bad log) killed every tick before it reached the healthy blobs behind it.
