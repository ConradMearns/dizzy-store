A device never fetches what would leave its filesystem under min_free_bytes.
tags: capacity, floor, principle-11, found-by-the-prod-outage
The store is rarely the only writer. On 2026-10-01 the server's disk filled with data the store did
not own while its own limit was fine; the floor is measured on the filesystem, not on the blobs.
