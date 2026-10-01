"""Shared helpers for the store's elements (the lib/python-uv/cas.py pattern:
one module at the lib root that every element can import).

Concerns, kept deliberately small:

- blob files   — the sharded ``<aa>/<bb>/<sha256>`` layout, atomic writes, and the
                 one rule that a "hash" must LOOK like one before it becomes a path
- LWW          — deterministic last-writer-wins for the few multi-writer facts
- placement    — "who holds this, and is it safe to drop mine?", the one place
                 the safety rules of store.feat.yaml principles 7-8 live, so the
                 queries and the evict procedure cannot disagree
- read models  — the indexes the generated schema cannot declare, and the crash
                 marker that says "a fold may be incomplete: rebuild on start"
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

_HEX64 = re.compile(r"[0-9a-f]{64}")


class NotAStore(FileNotFoundError):
    """There is no store at this path: its ``.store/`` identity is missing. At start-up
    that is a configuration problem (an unmounted drive, a wrong path), never something to
    fix by creating directories — `init` is the only thing that makes a store."""


class RootVanished(RuntimeError):
    """The store's root was there and is no longer the same filesystem: a drive was
    unplugged, unmounted or swapped. Not recoverable by mkdir — writing on would put blobs
    on the wrong disk (or in RAM) and record them as stored. The daemon must stop."""


class OutOfSpace(OSError):
    """The device is at (or past) a space limit and will not take more bytes in: its own
    limit_bytes, or the free-space floor its filesystem must keep (principle 11)."""


class PeerUnreachable(Exception):
    """A peer could not be reached (asleep, partitioned, wrong address).

    Reachability is observation, not fact (principle 10): procedures catch
    this, report it to peer_health, and move on — they never record it."""


class Throttle:
    """A token bucket limiting bytes per second (0 = unlimited): ``wait(n)`` after
    moving n bytes sleeps just long enough to hold the average rate. Used by
    replicate_blob (env.max_bytes_per_sec) and scrub (env.scrub_bytes_per_sec) so a
    sync never saturates a small server's uplink or disk."""

    def __init__(self, bytes_per_sec: int, clock=time.monotonic, sleep=time.sleep):
        self.rate = max(0, int(bytes_per_sec))
        self._clock, self._sleep = clock, sleep
        self._tokens = float(self.rate)          # one second's budget to start with
        self._last = clock()

    def wait(self, nbytes: int) -> None:
        if self.rate <= 0:
            return
        now = self._clock()
        self._tokens = min(float(self.rate), self._tokens + (now - self._last) * self.rate)
        self._last = now
        self._tokens -= nbytes
        if self._tokens < 0:
            self._sleep(-self._tokens / self.rate)
            self._last = self._clock()
            self._tokens = 0.0


# ── human sizes and durations ────────────────────────────────────────────────

_SIZE = re.compile(r"^\s*(\d+)\s*(b|kb|mb|gb|tb)?\s*$", re.I)
_UNITS = {"": 1, "b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "tb": 1024 ** 4}
_DURATION = re.compile(r"^\s*(\d+)\s*(s|m|h|d)\s*$", re.I)


def parse_size(value) -> int:
    """``4KB`` / ``20GB`` / ``1048576`` -> bytes (binary units)."""
    if isinstance(value, int):
        return value
    m = _SIZE.match(str(value))
    if not m:
        raise ValueError(f"bad size {value!r} (use 100, 4KB, 2MB, 20GB)")
    return int(m.group(1)) * _UNITS[(m.group(2) or "").lower()]


def parse_duration(value) -> timedelta:
    """``30s`` / ``10m`` / ``2h`` / ``3d`` -> timedelta."""
    m = _DURATION.match(str(value))
    if not m:
        raise ValueError(f"bad duration {value!r} (use 30s, 10m, 2h, 3d)")
    return timedelta(seconds=int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2).lower()])


# ── time ─────────────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """UTC, tzinfo dropped — the form SQLite round-trips, so comparisons never
    mix aware and naive datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def is_fresh(occurred_at: datetime, window_s: int, now: Optional[datetime] = None) -> bool:
    """Principle 9: policies act on fresh facts only. ``window_s <= 0`` means
    no window (every fact is fresh) — for configs that opt out."""
    if window_s <= 0:
        return True
    age = naive_utc(now or now_utc()) - naive_utc(occurred_at)
    return age <= timedelta(seconds=window_s)


def strictly_after(at: datetime, previous: Optional[datetime | str]) -> datetime:
    """``at`` — or, if that is not later than ``previous``, one microsecond after
    it. A device uses this for every last-writer-wins fact about a subject it has
    already spoken of, so its later word always beats its earlier one whatever the
    clock's resolution (or a step backwards); the payload-digest tie-break is for
    DIFFERENT writers only."""
    if not previous:
        return at
    if isinstance(previous, str):
        previous = datetime.fromisoformat(previous)
    if naive_utc(at) > naive_utc(previous):
        return at
    # always UTC-aware, like every other timestamp this feature writes to the log
    return naive_utc(previous).replace(tzinfo=timezone.utc) + timedelta(microseconds=1)


def iso(dt: Optional[datetime]) -> str:
    return naive_utc(dt).isoformat() if dt is not None else ""


# ── blob files ───────────────────────────────────────────────────────────────

def blob_path(root: str | Path, blob_hash: str) -> Path:
    """The address of a blob under a sharded root. A hash must LOOK like one: a
    command or peer that names ``/etc/hostname`` or ``../x`` as a "hash" would
    otherwise get that path back — and evict_blob would unlink it."""
    if not is_hash(blob_hash):
        raise ValueError(f"not a sha256: {str(blob_hash)[:80]!r}")
    return Path(root) / blob_hash[:2] / blob_hash[2:4] / blob_hash


def is_hash(name: object) -> bool:
    """A lowercase sha256 hex digest — the WHOLE string (a '$'-anchored match would
    let a trailing newline through), and only a string."""
    return isinstance(name, str) and _HEX64.fullmatch(name) is not None


def sha256_file(path: str | Path, bufsize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(bufsize):
            h.update(chunk)
    return h.hexdigest()


def iter_blobs(root: str | Path) -> Iterator[tuple[str, Path, int]]:
    """Every blob under a sharded root as (hash, path, size). Skips dot dirs
    (state_dir lives at <root>/.store/) and anything not named by a sha256."""
    base = Path(root)
    if not base.is_dir():
        return
    for a in sorted(base.iterdir()):
        if a.name.startswith(".") or not a.is_dir():
            continue
        for b in sorted(a.iterdir()):
            if not b.is_dir():
                continue
            for f in sorted(b.iterdir()):
                if is_hash(f.name) and f.is_file():
                    yield f.name, f, f.stat().st_size


def used_bytes(root: str | Path) -> int:
    return sum(size for _h, _p, size in iter_blobs(root))


def ensure_dir(path: str | Path, below: str | Path) -> Path:
    """``mkdir -p path`` — but never create ``below`` (or anything above it): it must
    already be there. A root's state directory is the proof the root is still the store it
    was; recreating a vanished mountpoint's directories would silently write on the wrong
    filesystem."""
    below = Path(below)
    if not below.is_dir():
        raise RootVanished(f"{below} is gone — refusing to recreate it")
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def place_atomic(src: str | Path, dest: str | Path) -> None:
    """Move a finished, verified file into its address — atomic on one
    filesystem, which is why tmp_dir must live beside root. ``dest`` is a blob address
    (<root>/<aa>/<bb>/<sha256>): its two shard directories are made on demand, the root
    never is."""
    dest = Path(dest)
    ensure_dir(dest.parent, dest.parents[2] / ".store")
    os.replace(src, dest)


FLOOR_MARGIN = 0.25      # relief goes this fraction of the floor past it, so a node just back over does not flap


def capacity_pressure(held: int, free: int, store) -> int:
    """Bytes to free (0 = no pressure), the ONE definition (principle 11): held blobs past
    the HIGH watermark of limit_bytes, or the filesystem's free space under min_free_bytes.
    Relief goes down to the LOW watermark, and to a quarter of the floor above it. check_capacity
    and the sweep both call this, so the event and the paced retry can never disagree."""
    need = 0
    limit = store.limit_bytes or 0
    if limit > 0 and held > limit * store.high_watermark:
        need = max(need, int(held - limit * store.low_watermark))
    floor = store.min_free_bytes or 0
    if floor > 0 and free < floor:
        need = max(need, int(floor * (1 + FLOOR_MARGIN)) - free)
    return need


def free_bytes(path: str | Path) -> int:
    """Bytes an ordinary (non-root) writer can still add on the filesystem holding
    ``path``: statvfs f_bavail, which excludes the blocks ext4 reserves for root."""
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def ensure_blob_file(src: str | Path, dest: str | Path, blob_hash: str,
                     tmp_dir: str | Path, link: bool = False) -> bool:
    """Make ``dest`` hold exactly the bytes of ``src`` (whose sha256 the caller has
    verified is ``blob_hash``) WITHOUT touching ``src``: copy through a temp file
    and place it atomically. A file already at ``dest`` is kept only if it IS
    those bytes (or is ``src`` itself — adoption in place); anything else there is
    replaced, so a stray file at the address can never pass for a verified copy.

    A copy is the default because a link shares bytes: an edit of the original
    would silently rewrite an "immutable" blob. ``link=True`` is the caller's
    promise that nothing edits ``src`` in place (a content-addressed tree is the
    case): it hard-links when ``src`` and the root share a filesystem — no extra
    space — and falls back to a copy when they do not. Returns True when it wrote."""
    dest = Path(dest)
    if dest.exists():
        try:
            if os.path.samefile(src, dest):
                return False
        except OSError:
            pass
        if sha256_file(dest) == blob_hash:
            return False
    tmp = ensure_dir(tmp_dir, Path(tmp_dir).parent)
    part = tmp / f"adopt-{blob_hash[:16]}.part"
    part.unlink(missing_ok=True)
    if link:
        try:
            os.link(src, part)
        except OSError:                                # another filesystem, or links refused
            link = False
        else:
            place_atomic(part, dest)                   # verified by the caller's hash of src
            return True
    shutil.copyfile(src, part)
    if sha256_file(part) != blob_hash:                 # the source changed under us
        part.unlink(missing_ok=True)
        raise ValueError(f"{src} changed while it was being copied")
    place_atomic(part, dest)
    return True


def valid_recipe(byte_size: int, chunk_size, chunk_hashes) -> bool:
    """Could this chunk recipe ever be fetched by? chunk_size > 0, exactly
    ceil(byte_size / chunk_size) hashes, each a sha256. No hashes = no recipe."""
    if not chunk_hashes:
        return not chunk_size                          # a chunk_size with no hashes is nonsense
    if not isinstance(chunk_size, int) or chunk_size <= 0 or byte_size <= 0:
        return False
    return len(chunk_hashes) == -(-byte_size // chunk_size) and all(is_hash(h) for h in chunk_hashes)


# ── last-writer-wins ─────────────────────────────────────────────────────────

def payload_digest(event) -> str:
    """A stable digest of an event's payload — the LWW tie-break. Projections
    cannot see the event id (seed dizzy-204a), but any two nodes hashing the
    same event get the same digest, which is all determinism needs."""
    body = json.dumps(event.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def lww_wins(new_at: datetime, new_digest: str,
             old_at: Optional[datetime], old_digest: Optional[str]) -> bool:
    """Does the new (occurred_at, digest) beat the stored one? Equal is not a
    win, so re-folding the same event is a no-op (idempotent)."""
    if old_at is None:
        return True
    return (naive_utc(new_at), new_digest) > (naive_utc(old_at), old_digest or "")


def loc_id(node_id: str, epoch: str, blob_hash: str) -> str:
    return f"{node_id}|{epoch}|{blob_hash}"


def scrub_id(node_id: str, epoch: str, collection: Optional[str]) -> str:
    return f"{node_id}|{epoch}|{collection or ''}"


# ── placement: who holds what, and is dropping mine safe ────────────────────

@dataclass
class Policy:
    min_sites: int = 1
    verify_max_age_days: int = 30
    evictable: bool = True
    declared: bool = False


def policy_for(session, collection: str) -> Policy:
    from gen_def.sqla.models.pool import CollectionPolicy
    row = session.get(CollectionPolicy, collection)
    if row is None:
        return Policy()
    return Policy(row.min_sites, row.verify_max_age_days, bool(row.evictable), True)


def _holders_query(session):
    from gen_def.sqla.models.pool import BlobLocation, Node
    return (session.query(BlobLocation, Node)
            .join(Node, (Node.node_id == BlobLocation.node_id)
                  & (Node.epoch == BlobLocation.epoch)))


def current_holders(session, blob_hash: str):
    """(BlobLocation, Node) for every location of a blob that is under its
    node's CURRENT epoch — a superseded life's claims never appear (principle 4)."""
    from gen_def.sqla.models.pool import BlobLocation
    return (_holders_query(session).filter(BlobLocation.blob_hash == blob_hash)
            .order_by(BlobLocation.node_id).all())


def copy_is_fresh(verified: Optional[datetime | str], policy: "Policy",
                  now: Optional[datetime] = None) -> bool:
    """Was this copy proven good within the collection's verify_max_age_days?"""
    if not verified:
        return False
    if isinstance(verified, str):
        verified = datetime.fromisoformat(verified)
    return naive_utc(now or now_utc()) - naive_utc(verified) <= timedelta(days=policy.verify_max_age_days)


def counts_toward_min_sites(state: str, draining: bool, verified, policy: "Policy",
                            now: Optional[datetime] = None) -> bool:
    """THE definition of a copy that counts (principles 7-8): it is 'present', its
    node is not draining, and it was proven good within the collection's window. The
    eviction candidates, the at-risk scan, the drain report AND the evict procedure's
    own log-side filter all call this, so they cannot disagree."""
    return state == "present" and not draining and copy_is_fresh(verified, policy, now)


class PlacementIndex:
    """Where every blob's copies are, loaded in ONE query (plus the scrub passes
    and the policies), so a placement question over tens of thousands of blobs is
    dictionary lookups, not tens of thousands of queries. ``counted_copies`` and
    ``safe_to_drop`` are the rule applied to those rows."""

    def __init__(self, session, blob_hashes=None):
        from gen_def.sqla.models.pool import BlobLocation, CollectionPolicy, ScrubState
        self.by_blob: dict[str, list] = defaultdict(list)
        query = _holders_query(session)
        if blob_hashes is None:
            rows = query.all()
        else:                                           # sqlite caps bound variables: batch
            wanted, rows = list(blob_hashes), []
            for i in range(0, len(wanted), 500):
                rows += query.filter(BlobLocation.blob_hash.in_(wanted[i:i + 500])).all()
        for loc, node in rows:
            self.by_blob[loc.blob_hash].append((loc, node))
        for holders in self.by_blob.values():
            holders.sort(key=lambda r: r[0].node_id)
        self._passes = {row.id: naive_utc(row.last_full_pass_at)
                        for row in session.query(ScrubState) if row.last_full_pass_at}
        self._policies = {row.collection: Policy(row.min_sites, row.verify_max_age_days,
                                                 bool(row.evictable), True)
                          for row in session.query(CollectionPolicy)}

    def policy(self, collection: str) -> "Policy":
        return self._policies.get(collection) or Policy()

    def holders(self, blob_hash: str) -> list:
        return self.by_blob.get(blob_hash, [])

    def verified_at(self, loc, collection: str) -> Optional[datetime]:
        """When a copy was last proven good: stored (verified on write) or the
        start of the latest full scrub pass covering its collection (principle 8)."""
        best = naive_utc(loc.stored_at)
        for key in (collection, ""):
            t = self._passes.get(scrub_id(loc.node_id, loc.epoch, key))
            if t is not None and (best is None or t > best):
                best = t
        return best

    def counted_copies(self, blob_hash: str, collection: str, now: Optional[datetime] = None,
                       exclude_node: Optional[str] = None):
        """Copies that COUNT toward min_sites: 'present', on a non-draining node,
        verified within verify_max_age_days. Returns [(loc, node)]."""
        policy = self.policy(collection)
        out = []
        for loc, node in self.holders(blob_hash):
            if node.node_id != exclude_node and counts_toward_min_sites(
                    loc.state, node.draining, self.verified_at(loc, collection), policy, now):
                out.append((loc, node))
        return out

    def safe_to_drop(self, me: str, blob_hash: str, collection: str, now: Optional[datetime] = None):
        """Would dropping node ``me``'s copy leave enough? OTHER nodes' counted
        copies must span at least min_sites distinct sites and include a non-draining
        always-on archive (a 'cold' drive never anchors — principle 7).
        Returns (ok, sites, anchor_present)."""
        copies = self.counted_copies(blob_hash, collection, now, exclude_node=me)
        sites = {n.site for _l, n in copies}
        anchor = any(n.role == "archive" for _l, n in copies)
        return (len(sites) >= self.policy(collection).min_sites and anchor), sites, anchor


def verified_at(session, loc, collection: str) -> Optional[datetime]:
    return PlacementIndex(session, [loc.blob_hash]).verified_at(loc, collection)


def counted_copies(session, blob_hash: str, collection: str, policy: "Policy" = None,
                   now: Optional[datetime] = None, exclude_node: Optional[str] = None):
    return PlacementIndex(session, [blob_hash]).counted_copies(blob_hash, collection, now, exclude_node)


def safe_to_drop(session, me: str, blob_hash: str, collection: str, policy: "Policy" = None,
                 now: Optional[datetime] = None):
    return PlacementIndex(session, [blob_hash]).safe_to_drop(me, blob_hash, collection, now)


# ── the read models: what the generated schema cannot declare ───────────────

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_location_blob ON BlobLocation (blob_hash)",
    "CREATE INDEX IF NOT EXISTS ix_location_node ON BlobLocation (node_id, epoch, state)",
    "CREATE INDEX IF NOT EXISTS ix_blob_collection ON Blob (collection)",
)
_STATE_TABLE = "CREATE TABLE IF NOT EXISTS StoreState (key TEXT PRIMARY KEY, value TEXT)"


def ensure_state_table(engine) -> None:
    """The one-row-per-flag table behind the crash marker and the read-model fingerprint. It is
    NOT a read model (nothing folds into it) and depends on no other table, so it can be read
    before the read models are trusted — which is the point: whether to trust them is decided from it."""
    with engine.begin() as conn:
        conn.exec_driver_sql(_STATE_TABLE)


def ensure_schema_extras(engine) -> None:
    """Indexes on the columns every placement question joins by (the generated models carry primary
    keys only — without these a per-blob lookup scans the whole location table). Only valid once the
    read-model tables have the shape this code expects."""
    ensure_state_table(engine)
    with engine.begin() as conn:
        for ddl in _INDEXES:
            conn.exec_driver_sql(ddl)


def read_flag(engine, key: str) -> Optional[str]:
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT value FROM StoreState WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def get_flag(session, key: str) -> Optional[str]:
    from sqlalchemy import text
    row = session.execute(text("SELECT value FROM StoreState WHERE key = :k"), {"k": key}).fetchone()
    return row[0] if row else None


def set_flag(session, key: str, value: str) -> None:
    from sqlalchemy import text
    session.execute(text("INSERT OR REPLACE INTO StoreState (key, value) VALUES (:k, :v)"),
                    {"k": key, "v": value})
    session.commit()


def parse_json_list(text: Optional[str]) -> list:
    if not text:
        return []
    try:
        v = json.loads(text)
    except ValueError:
        return []
    return v if isinstance(v, list) else []
