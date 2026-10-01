A large file is recorded once with its chunk recipe and fetched as verified chunks.
tags: chunking, replication, principle-6
Only blob_registered carries the chunk hashes; the laptop assembles the file
from verified chunks and records exactly one blob_stored when it is whole.
