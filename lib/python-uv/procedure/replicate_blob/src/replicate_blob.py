# Fetch one blob (a whole file, however chunked) from peers into local storage.
#
# Bytes are pulled by the receiver and VERIFIED: a blob is recorded as stored only
# when its sha256 matches its address. Chunked files come as chunks (asked of different
# peers in turn), each verified into a crash-surviving staging directory, and
# blob_stored is emitted ONCE, when the whole file is assembled.
import errno
import hashlib
import shutil
from pathlib import Path
from gen_int.python.procedure.replicate_blob_protocol import replicate_blob_protocol
from gen_int.python.procedure.replicate_blob_context import replicate_blob_context
from gen_def.pydantic.commands import ReplicateBlob
from gen_def.pydantic.events import BlobReplicationFailed, BlobStored
from gen_def.pydantic.query.get_blob import GetBlobInput
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput
from gen_def.pydantic.query.get_node_usage import GetNodeUsageInput
from gen_def.pydantic.telemetry import PeerHealth, TransferProgress
from storeutil import (PeerUnreachable, Throttle, blob_path, ensure_dir, now_utc,
                       place_atomic, sha256_file, valid_recipe)

_ROLE_PREFERENCE = {"archive": 0, "hot": 1, "cold": 2}
PROGRESS_STEP = 1 << 20        # report a transfer every MiB, not every 64 KiB read


def replicate_blob(
    context: replicate_blob_context,
    command: ReplicateBlob,
) -> None:
    store, peers = context.env.store, context.env.peers
    h = command.blob_hash
    final = blob_path(store.root, h)                  # refuses anything that is not a sha256
    replicas = context.query.get_blob_replicas(GetBlobReplicasInput(blob_hash=h))
    for node_id, state in zip(replicas.node_ids, replicas.states):
        if node_id == store.node_id and state == "present":
            return                               # idempotent: already held

    def fail(reason: str, from_node: str | None = None) -> None:
        context.emit.blob_replication_failed(BlobReplicationFailed(
            node_id=store.node_id, blob_hash=h, from_node=from_node, reason=reason,
            occurred_at=now_utc()))

    blob = context.query.get_blob(GetBlobInput(blob_hash=h))
    if not blob.found:
        return fail("not_held")                  # never registered: nothing to fetch
    if store.limit_bytes > 0:
        held = context.query.get_node_usage(GetNodeUsageInput(node_id=store.node_id)).held_bytes
        if held + blob.byte_size > store.limit_bytes:
            return fail("out_of_space")
    floor = store.min_free_bytes or 0
    if floor > 0 and context.env.disk.free_bytes() - blob.byte_size < floor:
        return fail("out_of_space")                # the filesystem, not just this store, must keep room
    throttle = Throttle(store.max_bytes_per_sec)

    # candidate sources: the hint first, then holders the log names, archives first
    holders = sorted(
        ((_ROLE_PREFERENCE.get(role, 3), node_id)
         for node_id, state, role in zip(replicas.node_ids, replicas.states, replicas.roles)
         if state == "present" and node_id != store.node_id))
    candidates = [n for _r, n in holders]
    if command.from_node and command.from_node != store.node_id:
        candidates = [command.from_node] + [n for n in candidates if n != command.from_node]

    # who actually has the bytes right now? (the log's claim is not enough)
    live: list[str] = []
    not_held: str | None = None
    for peer in candidates:
        try:
            size = peers.blob_size(peer, h)
        except PeerUnreachable as exc:
            context.telemetry.peer_health(PeerHealth(
                peer_id=peer, reachable=False, detail=str(exc)))
            continue
        context.telemetry.peer_health(PeerHealth(peer_id=peer, reachable=True))
        if size == blob.byte_size:
            live.append(peer)
        else:
            not_held = peer
    if not live:
        if not_held is not None:
            fail("not_held", not_held)           # reachable, but the bytes are not there
        return                                   # all unreachable: peer_link's business

    tmp = ensure_dir(store.tmp_dir, store.state_dir)
    part = tmp / f"{h}.part"
    # a recipe that could never be used (wrong chunk count, junk hashes) is ignored: the
    # whole file is fetched and verified against its address instead
    use_chunks = bool(blob.chunk_hashes) and valid_recipe(
        blob.byte_size, blob.chunk_size, list(blob.chunk_hashes))
    try:
        outcome = (_fetch_chunked(context, blob, live, part, tmp / f"{h}.chunks", throttle)
                   if use_chunks else _fetch_whole(context, blob, live, part, throttle))
    except OSError as exc:
        part.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            return fail("out_of_space")          # a full disk is a fact to record, not a crash
        raise
    if outcome[0] == "incomplete":
        return                                   # peers went quiet: staging kept for the next run
    if outcome[0] == "mismatch":
        return fail("hash_mismatch", outcome[1])
    place_atomic(part, final)
    context.emit.blob_stored(BlobStored(
        node_id=store.node_id, epoch=store.epoch, blob_hash=h,
        source=command.reason, occurred_at=now_utc()))


def _report(context, blob, peer: str, done: int, reported: int) -> int:
    """Transfer progress, at most once per MiB (and at the end)."""
    if done - reported >= PROGRESS_STEP or done == blob.byte_size:
        context.telemetry.transfer_progress(TransferProgress(
            blob_hash=blob.blob_hash, peer_id=peer, bytes_done=done, bytes_total=blob.byte_size))
        return done
    return reported


def _fetch_whole(context, blob, live, part: Path, throttle: Throttle):
    """Stream the file from the first peer that gives good bytes. Returns ('ok',),
    ('incomplete',) when no peer could supply it right now, or ('mismatch', peer)
    when a peer answered with bytes that are not the blob."""
    peers, h = context.env.peers, blob.blob_hash
    mismatch = None
    for peer in live:
        digest = hashlib.sha256()
        done = reported = 0
        try:
            with open(part, "wb") as out:
                for piece in peers.read_blob(peer, h):
                    out.write(piece)
                    digest.update(piece)
                    done += len(piece)
                    throttle.wait(len(piece))
                    reported = _report(context, blob, peer, done, reported)
        except PeerUnreachable as exc:
            context.telemetry.peer_health(PeerHealth(
                peer_id=peer, reachable=False, detail=str(exc)))
            continue
        if digest.hexdigest() == h:
            return ("ok",)
        mismatch = peer                           # a bad source: never a silent store
        part.unlink(missing_ok=True)
    return ("mismatch", mismatch) if mismatch is not None else ("incomplete",)


def _fetch_chunked(context, blob, live, part: Path, staging: Path, throttle: Throttle):
    """Fetch chunk by chunk (spread across the holders), each verified into a staging
    directory that survives a crash, then assemble and verify the whole. Returns the
    same shapes as _fetch_whole."""
    peers = context.env.peers
    ensure_dir(staging, staging.parent)
    h, size, chunk = blob.blob_hash, blob.byte_size, blob.chunk_size
    bad_peer = None
    for i, want in enumerate(blob.chunk_hashes):
        cpath = staging / f"{i:06d}"
        if cpath.exists() and sha256_file(cpath) == want:
            continue                              # a verified chunk survived a restart
        offset = i * chunk
        length = min(chunk, size - offset)
        got = False
        for k in range(len(live)):                # spread chunks across the holders
            peer = live[(i + k) % len(live)]
            try:
                data = b"".join(peers.read_blob(peer, h, offset=offset, length=length))
            except PeerUnreachable as exc:
                context.telemetry.peer_health(PeerHealth(
                    peer_id=peer, reachable=False, detail=str(exc)))
                continue
            if hashlib.sha256(data).hexdigest() != want:
                bad_peer = peer                   # this source sent a bad chunk
                continue
            cpath.write_bytes(data)
            throttle.wait(len(data))
            context.telemetry.transfer_progress(TransferProgress(
                blob_hash=h, peer_id=peer, bytes_done=min(size, offset + length),
                bytes_total=size))
            got = True
            break
        if not got:
            # every peer that answered sent bad bytes -> a fact worth recording; peers that
            # simply went quiet -> try again next sweep (the staging directory is kept)
            return ("mismatch", bad_peer) if bad_peer is not None else ("incomplete",)
    digest = hashlib.sha256()
    with open(part, "wb") as out:
        for i in range(len(blob.chunk_hashes)):
            piece = (staging / f"{i:06d}").read_bytes()
            out.write(piece)
            digest.update(piece)
    shutil.rmtree(staging, ignore_errors=True)
    if digest.hexdigest() != h:
        part.unlink(missing_ok=True)
        return ("mismatch", live[0])
    return ("ok",)
