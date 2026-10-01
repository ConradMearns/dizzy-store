A peer's same-size, bit-rotted copy is not proof: eviction needs the bytes to hash right.
tags: eviction, safety, principle-7, found-by-independent-review
The live check used to compare file SIZES, so a laptop whose copy had rotted in place
vouched for the server's last good one and the server deleted it. Peers are now asked
to re-hash their file (verify_blob). Fixed after review; the never-last-copy invariant fires without it.
