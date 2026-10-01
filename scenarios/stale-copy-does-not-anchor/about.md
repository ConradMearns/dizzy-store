A copy nobody has verified within verify_max_age_days is not a copy eviction may rely on.
tags: eviction, safety, freshness, principle-7, principle-8, found-by-independent-review
get_eviction_candidates applied the freshness window but evict_blob did not, so the two
disagreed: a stale peer could anchor a direct eviction that the at-risk scan then
reported as loss. Both now read the same verified_at.
