"""The paced sweep — bulk catch-up (store.feat.yaml principle 9).

Policies react to FRESH facts only; everything older — a peer's history after a
long sleep, a blob whose registration had not merged, a drain, pressure that
outlasted one reading — is this tick's job. Each tick makes at most
env.store.max_dispatch_per_event ATTEMPTS per kind, so a returning laptop is
caught up in paced steps, never a thundering herd.

It also keeps this device's own word current: if the log's card for this node
carries ANOTHER epoch, an older life of the device out-dated it (a replacement
drive with a dead clock announces "before" its predecessor and loses the
merge — and stale history triggers no policy), so it announces again, strictly
later than anything already said.

It also REMEMBERS what it could not do. A blob nobody can supply right now (its
only holder is asleep, its bytes are gone) or an eviction a peer will not vouch
for is backed off — one minute, then two, up to an hour — so the same failures at
the head of the list cannot starve everything behind them, and a poison blob
costs one attempt per backoff, not one per tick. An exception on one item is
reported and skipped, never allowed to end the tick.

Product code, not test code: the daemon's tick and the scenario runner's `sweep`
step both call it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gen_def.pydantic.telemetry import Progress
from storeutil import blob_path, capacity_pressure

BACKOFF_BASE_S = 60
BACKOFF_MAX_S = 3600


def sweep(node, cap: int | None = None) -> dict[str, int]:
    store = node.env_store
    cap = max(1, cap or store.max_dispatch_per_event)          # 0 must not mean "unbounded"
    done = {"replicated": 0, "evicted": 0, "failed": 0}
    me = node.query("get_node_profile", node_id=node.name)
    if me.found and me.epoch != node.epoch and node.cluster_id:
        node.announce()                       # my own word lost to an older life's: say it again, later
        me = node.query("get_node_profile", node_id=node.name)
    if not me.found:
        return done
    now = datetime.now(timezone.utc)
    memory = node.sweep_state

    def waiting(kind: str, blob_hash: str) -> bool:
        _fails, retry_after = memory.get((kind, blob_hash), (0, None))
        return retry_after is not None and now < retry_after

    def attempt(kind: str, blob_hash: str, command: str, succeeded, **fields) -> bool:
        try:
            node.run(command, blob_hash=blob_hash, **fields)
            ok = succeeded()
        except Exception as exc:                                # one bad item must not end the tick
            node._on_progress(Progress(
                stage="sweep_error", detail=f"{command} {blob_hash[:12]}: {type(exc).__name__}: {exc}"))
            ok = False
        if ok:
            memory.pop((kind, blob_hash), None)
        else:
            fails = memory.get((kind, blob_hash), (0, None))[0] + 1
            wait = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (fails - 1))
            memory[(kind, blob_hash)] = (fails, now + timedelta(seconds=wait))
            done["failed"] += 1
        return ok

    # catch up: fetch what this node should hold but does not
    backed = sum(1 for kind, _h in memory if kind == "replicate")
    missing = node.query("get_missing_blobs", node_id=node.name, limit=cap * 8 + backed)
    tried = 0
    for blob_hash in missing.blob_hashes or []:
        if tried >= cap:
            break
        if waiting("replicate", blob_hash):
            continue
        tried += 1
        if attempt("replicate", blob_hash, "replicate_blob",
                   lambda h=blob_hash: blob_path(store.root, h).is_file(), reason="backfill"):
            done["replicated"] += 1

    # relieve pressure / drain: drop what is safely elsewhere
    usage = node.query("get_node_usage", node_id=node.name)
    pressure = capacity_pressure(usage.held_bytes, node.disk.free_bytes(), store)
    if me.draining or (me.role == "hot" and pressure > 0):
        to_free = None if me.draining else pressure
        reason = "drain" if me.draining else "pressure"
        backed = sum(1 for kind, _h in memory if kind == "evict")
        candidates = node.query("get_eviction_candidates", node_id=node.name,
                                bytes_needed=to_free, limit=cap * 8 + backed,
                                min_bytes=store.min_evict_bytes)
        tried = 0
        for blob_hash in candidates.blob_hashes or []:
            if tried >= cap:
                break
            if waiting("evict", blob_hash):
                continue
            tried += 1
            if attempt("evict", blob_hash, "evict_blob",
                       lambda h=blob_hash: not blob_path(store.root, h).is_file(), reason=reason):
                done["evicted"] += 1
    return done
