# Bring an existing directory under management WITHOUT touching it. Every new file is
# hashed on the way in — a file whose bytes do not match the name a 'cas' tree claims
# is skipped and reported, never recorded (principle 5: stored means verified) — and
# copied into this node's sharded root (or hard-linked, on request, when nothing edits
# the originals in place). The originals are never moved or edited. A 'cas' file whose
# name this node already holds is skipped unread: scrub covers it, and a re-run of an
# adoption then costs a directory walk, not a re-read of the whole tree.
import os
from pathlib import Path
from gen_int.python.procedure.adopt_collection_protocol import adopt_collection_protocol
from gen_int.python.procedure.adopt_collection_context import adopt_collection_context
from gen_def.pydantic.commands import AdoptCollection
from gen_def.pydantic.events import BlobRegistered, BlobStored
from gen_def.pydantic.query.get_blob import GetBlobInput
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput
from gen_def.pydantic.telemetry import Progress
from storeutil import (Throttle, blob_path, ensure_blob_file, is_hash, iter_blobs,
                       sha256_file)

PROGRESS_EVERY = 500


def _walk_tree(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_file() and not path.is_symlink():
                yield path


def adopt_collection(
    context: adopt_collection_context,
    command: AdoptCollection,
) -> None:
    store = context.env.store
    if command.layout not in ("cas", "tree"):
        raise ValueError("layout must be 'cas' or 'tree'")
    root = Path(command.root)
    if not root.is_dir():
        raise ValueError(f"{root} is not a directory")
    paths = (p for _h, p, _s in iter_blobs(root)) if command.layout == "cas" else _walk_tree(root)
    throttle = Throttle(store.scrub_bytes_per_sec)
    scanned = recorded = skipped = 0
    seen: set[str] = set()       # emitted events fold only after this run returns
    def held_here(blob_hash: str) -> bool:
        replicas = context.query.get_blob_replicas(GetBlobReplicasInput(blob_hash=blob_hash))
        return any(n == store.node_id and st == "present"
                   for n, st in zip(replicas.node_ids, replicas.states))

    for path in paths:
        scanned += 1
        if command.layout == "cas" and is_hash(path.name) and held_here(path.name):
            continue                                   # already ours: not worth a re-read
        blob_hash = sha256_file(path)
        throttle.wait(path.stat().st_size)
        if command.layout == "cas" and blob_hash != path.name:
            skipped += 1
            context.telemetry.progress(Progress(
                stage="adopt", detail=f"skipped {path.name[:12]}: its bytes hash to {blob_hash[:12]}"))
            continue
        if scanned % PROGRESS_EVERY == 0:
            context.telemetry.progress(Progress(
                stage="adopt", detail=f"{command.collection}: hashed {scanned} files so far"))
        if blob_hash in seen:
            continue
        seen.add(blob_hash)
        if held_here(blob_hash):
            continue
        ensure_blob_file(path, blob_path(store.root, blob_hash), blob_hash, store.tmp_dir,
                         link=bool(command.link))
        if not context.query.get_blob(GetBlobInput(blob_hash=blob_hash)).found:
            context.emit.blob_registered(BlobRegistered(
                blob_hash=blob_hash, byte_size=path.stat().st_size, collection=command.collection,
                occurred_at=command.occurred_at))
        context.emit.blob_stored(BlobStored(
            node_id=store.node_id, epoch=store.epoch, blob_hash=blob_hash,
            source="adopted", occurred_at=command.occurred_at))
        recorded += 1
    context.telemetry.progress(Progress(
        stage="adopt",
        detail=f"{command.collection}: scanned {scanned}, recorded {recorded}, skipped {skipped}"))
