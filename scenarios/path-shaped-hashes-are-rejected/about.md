A blob hash that is not a lowercase sha256 never reaches the filesystem.
tags: validation, safety, found-by-independent-review
put_blob accepted '/tmp/x/precious.txt' as a hash and evict_blob then unlinked that file;
PeerSurface.read_blob('/etc/hostname') returned the file. blob_path itself now refuses.
