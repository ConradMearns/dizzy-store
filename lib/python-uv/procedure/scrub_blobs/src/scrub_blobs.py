# Integrity sweep: re-hash this node's held blobs within a byte budget, quarantine any
# whose bytes no longer match their address (or are gone, or unreadable), and record
# where the next run resumes. Reaching the end of the held set completes a pass.
import shutil
from datetime import datetime
from pathlib import Path
from gen_int.python.procedure.scrub_blobs_protocol import scrub_blobs_protocol
from gen_int.python.procedure.scrub_blobs_context import scrub_blobs_context
from gen_def.pydantic.commands import ScrubBlobs
from gen_def.pydantic.events import BlobCorrupt, ScrubCompleted
from gen_def.pydantic.query.get_blobs_held import GetBlobsHeldInput
from gen_def.pydantic.telemetry import Progress
from storeutil import Throttle, blob_path, ensure_dir, now_utc, sha256_file


def scrub_blobs(
    context: scrub_blobs_context,
    command: ScrubBlobs,
) -> None:
    store = context.env.store
    held = context.query.get_blobs_held(GetBlobsHeldInput(
        node_id=store.node_id, collection=command.collection))
    # a fresh pass starts now; a continuing one keeps its original start (freshness
    # is anchored to it — see the scrub_state_store projection)
    started = datetime.fromisoformat(held.pass_started_at) if held.pass_started_at else now_utc()
    throttle = Throttle(store.scrub_bytes_per_sec)
    checked = corrupt = bytes_checked = 0
    last = None
    complete = True
    for blob_hash, size in zip(held.blob_hashes or [], held.byte_sizes or []):
        if bytes_checked >= command.max_bytes:
            complete = False                      # budget spent: resume from `last`
            break
        path = blob_path(store.root, blob_hash)
        found: str | None = None
        bad = False
        try:
            if not path.is_file():
                bad = True
            else:
                found = sha256_file(path)
                nbytes = path.stat().st_size
                bytes_checked += nbytes
                throttle.wait(nbytes)
                bad = found != blob_hash
        except OSError:                           # unreadable is a bad copy, not a crash
            bad, found = True, None
        checked += 1
        last = blob_hash
        if bad:
            corrupt += 1
            try:
                if path.is_file():
                    quarantine = ensure_dir(store.quarantine_dir, store.state_dir)
                    shutil.move(str(path), str(quarantine / blob_hash))
            except OSError:
                pass                              # cannot move it aside: still say it is bad
            context.emit.blob_corrupt(BlobCorrupt(
                node_id=store.node_id, epoch=store.epoch, blob_hash=blob_hash,
                found_hash=found, occurred_at=now_utc()))
    context.telemetry.progress(Progress(
        stage="scrub", detail=f"checked {checked}, corrupt {corrupt}, complete={complete}"))
    context.emit.scrub_completed(ScrubCompleted(
        node_id=store.node_id, epoch=store.epoch, collection=command.collection,
        checked=checked, corrupt=corrupt, bytes_checked=bytes_checked,
        cursor=None if complete else last, pass_complete=complete,
        pass_started_at=started, occurred_at=now_utc()))
