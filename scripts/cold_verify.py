#!/usr/bin/env python3
"""Hash every blob of a CAS tree COLD and compare each with its own name.

A blob's name IS its SHA-256, so a file that hashes to its name is exactly the bytes it should be.
Each file's page cache is dropped (posix_fadvise DONTNEED, after a sync) before it is read, so the bytes
come off the disk, not out of RAM — a write that silently went wrong would show here. Also checks every
file sits at its address (aa/bb/<hash>) and lists anything in the tree that is not a blob.

    cold_verify.py ROOT            # exit 0 only if every file is intact and in place
"""
import hashlib, os, re, sys, time
from pathlib import Path

HEX64 = re.compile(r"[0-9a-f]{64}")


def main(root: str) -> int:
    root = Path(root)
    os.sync()
    blobs, strays = [], []
    for top in sorted(root.iterdir()):
        if top.name.startswith("."):
            continue                                   # .store/: the device's own state
        if not (top.is_dir() and re.fullmatch(r"[0-9a-f]{2}", top.name)):
            strays.append(str(top.relative_to(root)))
            continue
        for dirpath, _dirs, names in os.walk(top):
            for name in sorted(names):
                path = Path(dirpath) / name
                rel = path.relative_to(root)
                (blobs if HEX64.fullmatch(name) else strays).append(path if HEX64.fullmatch(name) else str(rel))
    bad, misplaced, total, started = [], [], 0, time.time()
    for i, path in enumerate(blobs, 1):
        name = path.name
        if path.relative_to(root) != Path(name[:2]) / name[2:4] / name:
            misplaced.append(str(path.relative_to(root)))
        fd = os.open(path, os.O_RDONLY)
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            digest = hashlib.sha256()
            while chunk := os.read(fd, 1 << 20):
                digest.update(chunk)
            total += os.fstat(fd).st_size
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)        # and do not let it crowd RAM
        finally:
            os.close(fd)
        if digest.hexdigest() != name:
            bad.append(f"{name} hashes to {digest.hexdigest()}")
        if i % 1000 == 0:
            print(f"  {i}/{len(blobs)} blobs, {total / 2**30:.1f} GiB, {total / 2**20 / (time.time() - started):.0f} MiB/s", flush=True)
    secs = time.time() - started
    print(f"{root}: {len(blobs)} blobs, {total:,} bytes, read cold in {secs:.0f}s ({total / 2**20 / max(secs, 1e-9):.0f} MiB/s)")
    print(f"  intact (hash == name): {len(blobs) - len(bad)}   CORRUPT: {len(bad)}   misplaced: {len(misplaced)}   not-a-blob: {len(strays)}")
    for line in (bad + misplaced + strays)[:10]:
        print("   !", line)
    return 0 if not (bad or misplaced) else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
