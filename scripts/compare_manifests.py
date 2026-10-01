#!/usr/bin/env python3
"""Compare blob manifests: do two or three places hold the same blobs, with the same sizes, at the right addresses?

A manifest is one line per blob, 'SIZE NAME RELPATH', which a content-addressed tree gives with

    (cd ROOT && find . -path ./.store -prune -o -type f -printf '%s %f %P\\n') > NAME.txt

(ssh into a remote one the same way — it reads metadata only). Then:

    compare_manifests.py server server.txt laptop laptop.txt wd wd.txt

Exit 0 only if every place holds exactly the first one's blobs. Names are SHA-256 digests, so equal names plus
`cold_verify.py` on each tree is the whole proof that the copies are the same bytes.
"""
import re, sys
from pathlib import Path

HEX64 = re.compile(r"[0-9a-f]{64}")
def load(path):
    out, bad = {}, []
    for line in Path(path).read_text().splitlines():
        size, name, rel = line.split(" ", 2)
        if not HEX64.fullmatch(name) or rel != f"{name[:2]}/{name[2:4]}/{name}":
            bad.append(rel); continue
        out[name] = int(size)
    return out, bad

labels = sys.argv[1::2]; paths = sys.argv[2::2]
tables = {}
for label, path in zip(labels, paths):
    tables[label], bad = load(path)
    print(f"{label:8s} {len(tables[label]):6d} blobs  {sum(tables[label].values()):>16,} bytes   not-blob/misplaced: {len(bad)}")
base = labels[0]
ok = True
for label in labels[1:]:
    a, b = tables[base], tables[label]
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    sizes = [n for n in set(a) & set(b) if a[n] != b[n]]
    print(f"{base} vs {label}: only in {base}: {len(only_a)}, only in {label}: {len(only_b)}, size mismatches: {len(sizes)}")
    ok &= not (only_a or only_b or sizes)
print("ALL THREE HOLD THE SAME BLOBS WITH THE SAME SIZES" if ok and len(labels) == 3 else ("identical" if ok else "DIFFERENCES FOUND"))
sys.exit(0 if ok else 1)
