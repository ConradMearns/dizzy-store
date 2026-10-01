An unreadable or missing blob is a finding; it must not stop the pass that would report it.
tags: scrub, robustness, repair, principle-8, found-by-independent-review
One chmod-000 blob raised PermissionError out of scrub_blobs, so no pass ever completed, no
freshness was ever recorded, and after 31 days every blob on the node counted as at risk.
