Each chunk is verified on arrival; a bad one is taken from another holder, not accepted.
tags: chunking, integrity, fallback, principle-5, found-by-mutation
Without per-chunk checks a rotted holder's chunk lands in the assembly, the whole-file check
fails, and the fetch is lost even though a good holder was available the whole time.
