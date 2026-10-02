#!/usr/bin/env python3
"""Mutation testing for the store: break one safety rule at a time in a SCRATCH COPY of the
project and confirm the test suite goes red. A survivor is a hole in the tests, not in the code.

    python store/scripts/mutate.py                       # every mutation (about 10 minutes, 4 workers)
    python store/scripts/mutate.py evict: scrub          # only those whose label contains a word
    JOBS=8 python store/scripts/mutate.py                # more workers

Each mutation is (label, file under store/, exact old text, new text, tests to run). One that
no longer applies (the code moved) is reported UNAPPLIABLE — update the list with the code. Logic
mutations run the fast suite (simulation + unit tests); transport mutations also run the real-HTTP
and daemon tests. Exit status 1 when anything survives or cannot be applied.

The scratch copies live in a temp directory; `host/`, `ext/` and `dagstore/` are linked, never
copied, and never mutated.
"""
import os, queue, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

STORE = Path(__file__).resolve().parents[1]
REPO = STORE.parent
PY = str(STORE / ".venv/bin/python") if (STORE / ".venv/bin/python").exists() else sys.executable
FAST = ["tests/test_scenarios.py", "tests/test_wiring.py", "tests/test_storeutil.py",
        "tests/test_recovery.py", "tests/test_fetch.py", "tests/test_projections.py",
        "tests/test_adopt_put.py", "tests/test_scrub.py", "tests/test_sweep.py",
        "tests/test_transport_units.py", "tests/test_guards.py", "tests/test_floor.py", "tests/test_min_evict.py",
        "tests/test_config.py", "tests/test_device_settings.py", "tests/test_cli_config.py",
        "tests/test_fingerprint.py", "tests/test_service.py", "tests/test_reload.py",
        "tests/test_doctor.py", "tests/test_eject.py", "tests/test_volumes.py", "tests/test_tool.py",
        "tests/test_drives.py", "tests/test_lock.py"]
IDLE = ["tests/test_idle_rules.py", "tests/test_idle.py"]          # `run --until-idle`: exact timing rules, then real sockets
HTTP = ["tests/test_scenarios_http.py", "tests/test_daemon.py", "tests/test_transport_units.py"]

M = []   # (label, relpath under store/, old, new, test_files)
def m(label, path, old, new, tests=FAST):
    M.append((label, path, old, new, tests))

LIB = "lib/python-uv/"
EV = LIB + "procedure/evict_blob/src/evict_blob.py"
RB = LIB + "procedure/replicate_blob/src/replicate_blob.py"
SB = LIB + "procedure/scrub_blobs/src/scrub_blobs.py"
AD = LIB + "procedure/adopt_collection/src/adopt_collection.py"
PB = LIB + "procedure/put_blob/src/put_blob.py"
SU = LIB + "storeutil.py"
ND = "src/dizzy_store/node.py"
SW = "src/dizzy_store/sweep.py"

# ── storeutil: the rules every safety question goes through
m("is_hash: unanchored (accepts longer strings)", SU, "_HEX64.fullmatch(name) is not None", "_HEX64.match(name) is not None")
m("is_hash: accepts non-strings", SU, "return isinstance(name, str) and _HEX64", "return _HEX64")
m("blob_path: no hash guard", SU, '    if not is_hash(blob_hash):\n        raise ValueError(f"not a sha256: {str(blob_hash)[:80]!r}")\n', "")
m("ensure_blob_file: stray at address believed", SU, "        if sha256_file(dest) == blob_hash:\n            return False", "        return False")
m("ensure_blob_file: copy not verified", SU, "    if sha256_file(part) != blob_hash:", "    if False:")
m("ensure_blob_file: link never used", SU, "    if link:\n        try:", "    if False:\n        try:")
m("ensure_blob_file: always links", SU, "    dest = Path(dest)\n    if dest.exists():\n        try:\n            if os.path.samefile", "    link = True\n    dest = Path(dest)\n    if dest.exists():\n        try:\n            if os.path.samefile")
m("valid_recipe: wrong count accepted", SU, "return len(chunk_hashes) == -(-byte_size // chunk_size) and", "return len(chunk_hashes) >= 1 and")
m("valid_recipe: zero chunk size accepted", SU, "chunk_size <= 0 or byte_size <= 0", "chunk_size < 0 or byte_size < 0")
m("valid_recipe: junk hashes accepted", SU, "and all(is_hash(h) for h in chunk_hashes)", "")
m("copy_is_fresh: boundary exclusive", SU, "<= timedelta(days=policy.verify_max_age_days)", "< timedelta(days=policy.verify_max_age_days)")
m("copy_is_fresh: unverified is fresh", SU, "    if not verified:\n        return False\n    if isinstance(verified, str):", "    if not verified:\n        return True\n    if isinstance(verified, str):")
m("counts: draining nodes count", SU, 'return state == "present" and not draining and copy_is_fresh', 'return state == "present" and copy_is_fresh')
m("counts: staleness ignored", SU, 'return state == "present" and not draining and copy_is_fresh(verified, policy, now)', 'return state == "present" and not draining')
m("counts: non-present counts", SU, 'return state == "present" and not draining', 'return not draining')
m("verified_at: scrub passes ignored", SU, '        for key in (collection, ""):', "        for key in ():")
m("verified_at: stored_at ignored", SU, "        best = naive_utc(loc.stored_at)", "        best = None")
m("holders: epoch join removed (old lives count)", SU, "            .join(Node, (Node.node_id == BlobLocation.node_id)\n                  & (Node.epoch == BlobLocation.epoch)))", "            .join(Node, (Node.node_id == BlobLocation.node_id)))")
m("safe_to_drop: any node anchors", SU, 'anchor = any(n.role == "archive" for _l, n in copies)', "anchor = bool(copies)")
m("safe_to_drop: counts nodes not sites", SU, "return (len(sites) >= self.policy(collection).min_sites and anchor), sites, anchor", "return (len(copies) >= self.policy(collection).min_sites and anchor), sites, anchor")
m("safe_to_drop: anchor not required", SU, "and anchor), sites, anchor", "), sites, anchor")
m("strictly_after: equal instant not bumped", SU, "    if naive_utc(at) > naive_utc(previous):", "    if naive_utc(at) >= naive_utc(previous):")
m("strictly_after: never bumps", SU, "    if naive_utc(at) > naive_utc(previous):\n        return at", "    if True:\n        return at")
m("lww: digest tie-break ignored", SU, 'return (naive_utc(new_at), new_digest) > (naive_utc(old_at), old_digest or "")', "return naive_utc(new_at) > naive_utc(old_at)")
m("policy default: not evictable", SU, "    evictable: bool = True\n    declared: bool = False", "    evictable: bool = False\n    declared: bool = False")
m("policy default: min_sites 2", SU, "    min_sites: int = 1\n", "    min_sites: int = 2\n")
m("schema extras: indexes dropped", SU, "        for ddl in _INDEXES:\n            conn.exec_driver_sql(ddl)", "        pass")

# ── evict_blob
m("evict: non-evictable collections evicted", EV, '    if not policy.evictable:\n        return refuse("collection is not evictable")\n', "")
m("evict: pressure allowed on archive", EV, '    if command.reason == "pressure" and me.role != "hot":\n        return refuse("only a hot node evicts under pressure")\n', "")
m("evict: drain allowed without draining", EV, '    if command.reason == "drain" and not me.draining:\n        return refuse("only a draining node evicts to drain")\n', "")
m("evict: cold node may evict", EV, '    if me.role == "cold":\n        return refuse("a cold device never evicts")\n', "")
m("evict: unknown reason accepted", EV, '    if command.reason not in ("pressure", "drain"):\n        return refuse(f"unknown reason {command.reason!r}")\n', "")
m("evict: wanted collection evicted under pressure", EV, '    if command.reason == "pressure" and ("*" in wants or blob.collection in wants):\n        return refuse("this node wants that collection in full")\n', "")
m("evict: pinned blob evicted", EV, '    if mine[0][2]:\n        return refuse("pinned")\n', "")
m("evict: stale peers count (log side)", EV, "if r[0] != store.node_id and counts_toward_min_sites(r[1], r[5], r[6], window, now)]", "if r[0] != store.node_id and r[1] == 'present' and not r[5]]")
m("evict: peer's file not re-hashed", EV, 'if not proof or not proof.get("held") or proof.get("draining"):', 'if not proof or proof.get("draining"):')
m("evict: peer's live draining ignored", EV, 'if not proof or not proof.get("held") or proof.get("draining"):', 'if not proof or not proof.get("held"):')
m("evict: archive anchor taken from the log not the proof", EV, 'anchor = anchor or proof.get("role") == "archive"', "anchor = anchor or _role == 'archive'")
m("evict: no anchor required", EV, "    if len(proven_sites) < policy.min_sites or not anchor:", "    if len(proven_sites) < policy.min_sites:")
m("evict: min_sites off by one", EV, "    if len(proven_sites) < policy.min_sites or not anchor:", "    if len(proven_sites) < policy.min_sites - 1 or not anchor:")
m("evict: unreachable peer counts as proof", EV, "        except PeerUnreachable as exc:\n            context.telemetry.peer_health(PeerHealth(\n                peer_id=node_id, reachable=False, detail=str(exc)))\n            continue\n        context.telemetry.peer_health(PeerHealth(peer_id=node_id, reachable=True))", "        except PeerUnreachable as exc:\n            proof = {'held': True, 'size': blob.byte_size, 'role': 'archive'}\n        context.telemetry.peer_health(PeerHealth(peer_id=node_id, reachable=True))")
m("evict: bytes never deleted", EV, "    path.unlink(missing_ok=True)\n", "")
m("evict: confirmed_sites recorded as 0", EV, "confirmed_sites=len(proven_sites)", "confirmed_sites=0")

# ── replicate_blob
m("replicate: whole file not verified", RB, "        if digest.hexdigest() == h:\n            return (\"ok\",)", "        if True:\n            return (\"ok\",)")
m("replicate: chunk not verified", RB, "            if hashlib.sha256(data).hexdigest() != want:", "            if False:")
m("replicate: assembled file not verified", RB, "    if digest.hexdigest() != h:\n        part.unlink(missing_ok=True)", "    if False:\n        part.unlink(missing_ok=True)")
m("replicate: bad recipe trusted", RB, "    use_chunks = bool(blob.chunk_hashes) and valid_recipe(\n        blob.byte_size, blob.chunk_size, list(blob.chunk_hashes))", "    use_chunks = bool(blob.chunk_hashes)")
m("replicate: ENOSPC not recorded", RB, "        if exc.errno == errno.ENOSPC:", "        if False:")
m("replicate: limit check removed", RB, "        if held + blob.byte_size > store.limit_bytes:\n            return fail(\"out_of_space\")", "        pass")
m("replicate: mismatch silent", RB, "    if outcome[0] == \"mismatch\":\n        return fail(\"hash_mismatch\", outcome[1])", "    if outcome[0] == \"mismatch\":\n        return")
m("replicate: staging kept on incomplete lost", RB, '    if outcome[0] == "incomplete":\n        return ', '    if outcome[0] == "incomplete":\n        shutil.rmtree(tmp / f"{h}.chunks", ignore_errors=True)\n        return ')
m("replicate: sources not liveness-checked", RB, "        if size == blob.byte_size:\n            live.append(peer)", "        if True:\n            live.append(peer)")
m("replicate: idempotency removed", RB, '        if node_id == store.node_id and state == "present":\n            return                               # idempotent: already held\n', "")
m("replicate: cold peers preferred", RB, '_ROLE_PREFERENCE = {"archive": 0, "hot": 1, "cold": 2}', '_ROLE_PREFERENCE = {"archive": 2, "hot": 1, "cold": 0}')
m("replicate: stored source mislabeled", RB, "source=command.reason, occurred_at=now_utc()))", "source='upload', occurred_at=now_utc()))")

# ── scrub
m("scrub: budget off by one", SB, "if bytes_checked >= command.max_bytes:", "if bytes_checked > command.max_bytes:")
m("scrub: cursor always reset", SB, "cursor=None if complete else last,", "cursor=None,")
m("scrub: pass always complete", SB, "pass_complete=complete,", "pass_complete=True,")
m("scrub: no quarantine", SB, "                    shutil.move(str(path), str(quarantine / blob_hash))", "                    pass")
m("scrub: missing file not flagged", SB, "            if not path.is_file():\n                bad = True", "            if not path.is_file():\n                bad = False")
m("scrub: unreadable file crashes the pass", SB, "        except OSError:                           # unreadable is a bad copy, not a crash\n            bad, found = True, None", "        except ZeroDivisionError:\n            bad, found = True, None")
m("scrub: freshness anchored to completion not start", SB, "started = datetime.fromisoformat(held.pass_started_at) if held.pass_started_at else now_utc()", "started = now_utc()")

# ── adopt / put
m("adopt: names trusted, bytes not hashed", AD, "        blob_hash = sha256_file(path)\n        throttle.wait", "        blob_hash = path.name if is_hash(path.name) else sha256_file(path)\n        throttle.wait")
m("adopt: lying names recorded", AD, '        if command.layout == "cas" and blob_hash != path.name:', "        if False:")
m("adopt: held names re-read", AD, '        if command.layout == "cas" and is_hash(path.name) and held_here(path.name):\n            continue', "        pass")
m("adopt: link request ignored", AD, "link=bool(command.link))", "link=False)")
m("adopt: always links", AD, "link=bool(command.link))", "link=True)")
m("adopt: already-held skip removed", AD, "        if held_here(blob_hash):\n            continue\n", "")
m("adopt: always re-registers", AD, "if not context.query.get_blob(GetBlobInput(blob_hash=blob_hash)).found:", "if True:")
m("adopt: duplicate content re-recorded", AD, "        if blob_hash in seen:\n            continue\n", "")
m("put: size check removed", PB, "    if not path.is_file() or path.stat().st_size != command.byte_size:", "    if not path.is_file():")
m("put: bad recipe accepted", PB, "        if not valid_recipe(command.byte_size, command.chunk_size, list(command.chunk_hashes or [])):", "        if False:")
m("put: idempotency removed", PB, '        if node_id == store.node_id and state == "present":\n            return', "        if False:\n            return")

# ── projections
CAT = LIB + "projection/blob_catalog_store/src/blob_catalog_store.py"
SCR = LIB + "projection/scrub_state_store/src/scrub_state_store.py"
m("catalog: first-folded wins", CAT, "        if key < (row.first_seen_at, row.digest):", "        if False:")
m("catalog: latest registration wins", CAT, "        if key < (row.first_seen_at, row.digest):", "        if key > (row.first_seen_at, row.digest):")
m("catalog: recipe never filled in", CAT, "        if has_recipe and (row.chunk_hashes_json is None\n                           or key < (row.chunk_at, row.chunk_digest)):", "        if False:")
m("scrub fold: freshness stamped at event time", SCR, "    started = naive_utc(event.pass_started_at or event.occurred_at)", "    started = naive_utc(event.occurred_at)")
m("scrub fold: older pass overwrites newer", SCR, "        if row.last_full_pass_at is None or started > row.last_full_pass_at:", "        if True:")
m("scrub fold: cursor not saved", SCR, "        row.cursor = event.cursor\n", "        row.cursor = None\n")

# ── queries
GEC = LIB + "query/get_eviction_candidates/src/get_eviction_candidates.py"
m("candidates: wanted collections offered", GEC, '        if not me.draining and ("*" in wants or blob.collection in wants):\n            continue', "        pass")
m("candidates: never-read before read (two timelines)", GEC, "mine.sort(key=lambda lb: (lb[0].last_access_at or lb[0].stored_at, lb[1].blob_hash))", "mine.sort(key=lambda lb: (lb[0].last_access_at is not None, lb[0].last_access_at or lb[0].stored_at, lb[1].blob_hash))")
m("candidates: most recent first", GEC, "mine.sort(key=lambda lb: (lb[0].last_access_at or lb[0].stored_at, lb[1].blob_hash))", "mine.sort(key=lambda lb: (lb[0].last_access_at or lb[0].stored_at, lb[1].blob_hash), reverse=True)")
m("candidates: pinned offered", GEC, "BlobLocation.state == \"present\", BlobLocation.pinned.is_(False)).all())", "BlobLocation.state == \"present\").all())")
m("candidates: non-evictable offered", GEC, "        if not index.policy(blob.collection).evictable:\n            continue\n", "")
m("candidates: bytes_needed ignored", GEC, "        if (not me.draining and input.bytes_needed is not None\n                and covered >= input.bytes_needed):\n            break\n", "")
m("candidates: limit ignored", GEC, "        if input.limit and len(out) >= input.limit:\n            break\n", "")
m("candidates: cold nodes offered", GEC, '    if me is None or me.role == "cold" or not (me.draining or me.role == "hot"):', '    if me is None or not (me.draining or me.role == "hot"):')
m("candidates: archives offered", GEC, "not (me.draining or me.role == \"hot\")", "False")
m("at_risk: collection filter ignored", LIB + "query/get_at_risk_blobs/src/get_at_risk_blobs.py", "    if input.collection:\n        q = q.filter(Blob.collection == input.collection)\n", "")
m("at_risk: stale copies counted", LIB + "query/get_at_risk_blobs/src/get_at_risk_blobs.py", "index.counted_copies(blob.blob_hash, blob.collection, now)", "[(l, n) for l, n in index.holders(blob.blob_hash) if l.state == 'present']")
m("drain: pinned not unsafe", LIB + "query/get_drain_remaining/src/get_drain_remaining.py", "if loc.pinned or not index.policy(blob.collection).evictable or not ok:", "if not index.policy(blob.collection).evictable or not ok:")
m("held: cursor ignored", LIB + "query/get_blobs_held/src/get_blobs_held.py", "    if cursor:\n        q = q.filter(BlobLocation.blob_hash > cursor)\n", "")
m("missing: draining node is a target", LIB + "query/get_missing_blobs/src/get_missing_blobs.py", "    if me is None or me.draining:", "    if me is None:")
m("replicas: verified_at wrong (stored only)", LIB + "query/get_blob_replicas/src/get_blob_replicas.py", "verified_ats=[iso(index.verified_at(l, collection)) for l, _n in rows]", "verified_ats=[iso(l.stored_at) for l, _n in rows]")

# ── node + sweep
m("node: peers' verify never re-hashes", ND, "            held = sha256_file(path) == blob_hash", "            held = True")
m("node: peers' verify hides draining", ND, 'live = {"role": card.get("role"), "draining": bool(card.get("draining"))}', 'live = {"role": card.get("role"), "draining": False}')
m("node: no reaction budget per merge", ND, "            if budget[envelope.type] > 0:", "            if True:")
m("node: crash marker never set", ND, '            set_flag(self.session, DIRTY, "1")', "            pass")
m("node: marker cleared even after failure", ND, "            if outer and not self._unsafe_failed:", "            if outer:")
m("node: no rebuild on a marked start", ND, '        elif get_flag(self.session, DIRTY) == "1":\n            self.rebuild("the last run died mid-fold")', "        elif False:\n            pass")
m("node: emitted events stranded by a failure", ND, "        except BaseException:\n            self.engine._drain_events()\n            raise", "        except BaseException:\n            raise")
m("node: card not following announce", ND, "            self.card.update({k: v for k, v in fields.items() if k in CARD_KEYS and v is not None})", "            pass")
m("node: hot cache wants everything by default", ND, 'self.card["wants"] = [] if self.card["role"] == "hot" else ["*"]', 'self.card["wants"] = ["*"]')
m("sweep: no failure memory", SW, "        return retry_after is not None and now < retry_after", "        return False")
m("sweep: poison item ends the tick", SW, "        except Exception as exc:                                # one bad item must not end the tick", "        except ZeroDivisionError as exc:")
m("sweep: zero cap means unbounded", SW, "    cap = max(1, cap or store.max_dispatch_per_event)", "    cap = cap or store.max_dispatch_per_event or 10 ** 9")
m("sweep: superseded epoch not re-announced", SW, "    if me.found and me.epoch != node.epoch and node.cluster_id:", "    if False:")
# (no mutation for "a hot node sweeps for evictions without pressure": with no pressure the sweep asks the
#  candidates query for 0 bytes and it answers none — the guard and the query back each other up, so it is
#  an equivalent mutant)
m("sweep: drain mislabeled as pressure", SW, 'reason = "drain" if me.draining else "pressure"', 'reason = "pressure"')
m("sweep: backoff never grows", SW, "wait = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (fails - 1))", "wait = BACKOFF_BASE_S")
m("sweep: success keeps the backoff", SW, "            memory.pop((kind, blob_hash), None)", "            pass")

m("run-time: has_blob lets unreadable files crash", ND, "        except OSError:                                  # a file nobody can read is not a copy\n            return False", "        except ZeroDivisionError:\n            return False")
m("sweep: epoch re-announce does not bump", SU, "    return naive_utc(previous).replace(tzinfo=timezone.utc) + timedelta(microseconds=1)", "    return at")


# ── drive guardrails (stop when the root vanishes; never conjure one)
CFG = "src/dizzy_store/config.py"
DM = "src/dizzy_store/daemon.py"
DV = "src/dizzy_store/device.py"
DC = "src/dizzy_store/doctor.py"
EJ = "src/dizzy_store/eject.py"
VO = "src/dizzy_store/volumes.py"
CL = "src/dizzy_store/cli.py"
TL = "src/dizzy_store/tool.py"
SV = "src/dizzy_store/service.py"
m("guard: place_atomic recreates a vanished root", SU, '    ensure_dir(dest.parent, dest.parents[2] / ".store")\n', "    dest.parent.mkdir(parents=True, exist_ok=True)\n")
m("guard: ensure_dir creates what it must not", SU, "    if not below.is_dir():\n        raise RootVanished", "    if False:\n        raise RootVanished")
m("guard: node never checks its root", ND, "        if (st.st_dev, st.st_ino) != self._root_id:\n            raise RootVanished", "        if False:\n            raise RootVanished")
m("guard: a swapped filesystem is not noticed", ND, "        if (st.st_dev, st.st_ino) != self._root_id:", "        if st.st_dev != self._root_id[0] and False:")
m("guard: dispatch skips the root check", ND, "        self.guard_root()                        # before the read models are touched at all\n", "")
m("guard: a real device creates its own root", ND, "        else:                                    # a real device never conjures its own root\n            if not state.is_dir():", "        elif False:\n            if not state.is_dir():")
m("guard: daemon ignores a vanished root", DM, "        except RootVanished as exc:\n            self.fatal(exc)\n            return\n        if self._due(\"sync\", force):", "        except RootVanished:\n            return\n        if self._due(\"sync\", force):")
m("guard: fatal does not set the exit status", DM, "        self.exit_code = EX_IOERR\n", "        self.exit_code = 0\n")
m("guard: fatal does not stop the server", DM, "        self.stop.set()\n        if self.server is not None:\n            self.server.should_exit = True\n", "        self.stop.set()\n")
m("guard: init allowed on an unmounted path", CL, "    if not root.parent.is_dir():\n        raise ConfigError", "    if False:\n        raise ConfigError")
m("guard: init allowed on / under a drive path", CL, "str(root).startswith(_REMOVABLE_PREFIXES) and _same_filesystem(root.parent, \"/\")", "False")
m("guard: not-a-store is not 78", CL, "        return EX_CONFIG                         # systemd", "        return 1                                 # systemd")

# ── the free-space floor
m("floor: pressure ignores the floor", SU, "    if floor > 0 and free < floor:\n        need = max(need, int(floor * (1 + FLOOR_MARGIN)) - free)", "    pass")
m("floor: relief stops AT the floor (no margin)", SU, "FLOOR_MARGIN = 0.25", "FLOOR_MARGIN = 0.0")
m("floor: the limit is ignored", SU, "    if limit > 0 and held > limit * store.high_watermark:", "    if False:")
m("floor: a limit and a floor do not take the larger", SU, "        need = max(need, int(floor * (1 + FLOOR_MARGIN)) - free)", "        need = int(floor * (1 + FLOOR_MARGIN)) - free")
m("floor: fetches ignore the floor", RB, "    if floor > 0 and context.env.disk.free_bytes() - blob.byte_size < floor:", "    if False:")
m("floor: fetch compares free, not free minus the blob", RB, "context.env.disk.free_bytes() - blob.byte_size < floor", "context.env.disk.free_bytes() < floor")
m("floor: uploads ignore the floor", ND, "        if floor > 0 and self.disk.free_bytes() < floor:\n            raise OutOfSpace", "        if False:\n            raise OutOfSpace")
m("floor: check_capacity ignores the disk", LIB + "procedure/check_capacity/src/check_capacity.py", "    free = context.env.disk.free_bytes()", "    free = 10 ** 18")
m("floor: the sweep ignores the floor", SW, "    pressure = capacity_pressure(usage.held_bytes, node.disk.free_bytes(), store)", "    pressure = capacity_pressure(usage.held_bytes, 10 ** 18, store)")
m("floor: statvfs counts root's reserve", SU, "    return st.f_bavail * st.f_frsize", "    return st.f_bfree * st.f_frsize")

# ── min_evict_bytes: small blobs stay under pressure (a drain still takes them)
POL = LIB + "policy/evict_on_space_pressure/src/evict_on_space_pressure.py"
INV = "src/dizzy_store/invariants.py"
SC = "src/dizzy_store/scenario.py"
m("min_evict: candidates ignore the exemption", GEC, "        if not me.draining and blob.byte_size < (input.min_bytes or 0):\n            continue                      # ... nor a small blob (min_evict_bytes); a drain takes those too\n", "")
m("min_evict: candidates exempt a blob of exactly min_bytes", GEC, "blob.byte_size < (input.min_bytes or 0)", "blob.byte_size <= (input.min_bytes or 0)")
m("min_evict: a drain honours the exemption in the candidates", GEC, "        if not me.draining and blob.byte_size < (input.min_bytes or 0):", "        if blob.byte_size < (input.min_bytes or 0):")
m("min_evict: exempt blobs still count toward bytes_needed", GEC, "        if not me.draining and blob.byte_size < (input.min_bytes or 0):\n            continue", "        if not me.draining and blob.byte_size < (input.min_bytes or 0):\n            covered += blob.byte_size\n            continue")
m("min_evict: evict_blob ignores the exemption (asked by hand)", EV, '    if command.reason == "pressure" and (blob.byte_size or 0) < smallest:\n        return refuse(f"{blob.byte_size} bytes is under min_evict_bytes ({smallest}): small blobs stay")\n', "")
m("min_evict: evict_blob exempts a blob of exactly min_evict_bytes", EV, '(blob.byte_size or 0) < smallest', '(blob.byte_size or 0) <= smallest')
m("min_evict: evict_blob applies the exemption to a drain", EV, 'if command.reason == "pressure" and (blob.byte_size or 0) < smallest:', 'if (blob.byte_size or 0) < smallest:')
m("min_evict: the sweep does not pass the exemption", SW, "                                bytes_needed=to_free, limit=cap * 8 + backed,\n                                min_bytes=store.min_evict_bytes)\n", "                                bytes_needed=to_free, limit=cap * 8 + backed)\n")
m("min_evict: the pressure policy does not pass the exemption", POL, "        limit=store.max_dispatch_per_event, min_bytes=store.min_evict_bytes))", "        limit=store.max_dispatch_per_event))")
m("min_evict: a raw min_evict_bytes is not read as a size", CFG, 'SIZE_KEYS = {"limit_bytes", "min_free_bytes", "min_evict_bytes", "chunk_threshold_bytes", "chunk_size",', 'SIZE_KEYS = {"limit_bytes", "min_free_bytes", "chunk_threshold_bytes", "chunk_size",')
m("min_evict: the named setting never reaches env.store", CFG, '        if self.min_evict is not None:\n            out["min_evict_bytes"] = self.min_evict\n', "")
m("min_evict: an explicit 0 is ignored", CFG, "        if self.min_evict is not None:", "        if self.min_evict:")
m("min_evict: no default (a removed setting stays in force)", ND, "min_free_bytes=0, min_evict_bytes=0,", "min_free_bytes=0,")
m("min_evict: scenarios cannot spell the size", SC, '"min_free_bytes", "min_evict_bytes") else v', '"min_free_bytes") else v')
m("min_evict: the invariant is not registered", INV, '    "small-blobs-stay": small_blobs_stay_under_pressure,\n', "")
m("min_evict: the invariant flags a drain", INV, '                    or payload.get("reason") != "pressure"):', '                    or False):')
m("min_evict: the invariant forgives everything", INV, "            if blob is not None and blob.byte_size < smallest:", "            if False:")

# ── configuration: layering, resolution, the split between drive and machine
m("config: earlier files win", CFG, "            merged = _deep_merge(merged, _read(path))", "            merged = _deep_merge(_read(path), merged)")
m("config: mappings replace instead of merging", CFG, "        if key in out and isinstance(out[key], dict) and isinstance(value, dict):\n            out[key] = _deep_merge(out[key], value)", "        if False:\n            pass")
m("config: relative roots resolve against the cwd", CFG, "(path.parent / root).resolve()", "root.resolve()")
m("config: typos are accepted", CFG, 'model_config = ConfigDict(extra="forbid")', 'model_config = ConfigDict(extra="ignore")')
m("config: sizes are decimal", "lib/python-uv/storeutil.py", '"kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "tb": 1024 ** 4}', '"kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4}')
m("resolve: the environment beats a flag", CFG, "    if root:\n        return by_root(root)\n    if device:", "    if env.get('DIZZY_STORE_ROOT'):\n        return by_root(env['DIZZY_STORE_ROOT'])\n    if root:\n        return by_root(root)\n    if device:")
m("resolve: no reverse lookup by root", CFG, "            if dev.root and _same_dir(dev.root, path):", "            if False:")
m("resolve: device settings do not sit over the defaults", CFG, "        settings = cfg.devices[name].merged_under(cfg.defaults)", "        settings = cfg.devices[name]")
m("device: machine settings are baked into the drive", DV, '            return s.listen or h.get("listen") or d["listen"]', '            d["listen"] = s.listen or h.get("listen") or d["listen"]\n            return d["listen"]')
m("device: machine endpoints ignored in the card", DV, '                "endpoints": self["endpoints"]}', '                "endpoints": d["endpoints"]}')
m("device: config overrides ignored", DV, '            return {**(d.get("config") or {}), **s.env_store()}', '            return dict(d.get("config") or {})')
m("cli: init takes the machine's listen into the drive", CL, 'location_note=args.location_note, listen=args.listen,', 'location_note=args.location_note, listen=args.listen or resolved.settings.listen,')

# ── reload, readiness and clean stops
m("reload: a bad file replaces the running config", DM, "        except ConfigError as exc:\n            log.error(\"reload refused", "        except ZeroDivisionError as exc:\n            log.error(\"reload refused")
m("reload: removed settings stay in force", DM, "            env = {**DEFAULT_CONFIG, **now[\"config\"]}", "            env = dict(now[\"config\"])")
m("reload: the card is never re-announced", DM, "            if card != {k: self.node.card.get(k) for k in card}:", "            if False:")
m("reload: listen can change under a bound socket", DM, "                device.settings = device.settings.model_copy(update={\"listen\": old.listen})", "                pass")
m("reload: the loop never looks at the flag", DM, "            if self._reload.is_set():\n                self._reload.clear()\n                self.reload()", "            pass")
m("reload: seeds are not updated live", DM, "                self.node.peers.set_seeds(now[\"seeds\"])", "                pass")
m("serve: SIGTERM kills the process instead of returning", DM, "        for sig in (signal.SIGTERM, signal.SIGINT):\n            saved[sig] = signal.signal(sig, stop_on)", "        pass")
m("serve: no STOPPING notification", DM, '        notify("STOPPING=1")', "        pass")
m("serve: READY is sent before the listener is up", DM, "    while not server.started and not daemon.stop.is_set() and time.monotonic() < deadline:", "    while False:")
m("serve: SIGHUP never reloads", DM, "        saved[signal.SIGHUP] = signal.signal(signal.SIGHUP, lambda *_: daemon.request_reload())", "        pass")
m("unit: exit 78 restarts forever", SV, "RestartPreventExitStatus=78\n", "")
m("unit: not a notify service", SV, "Type=notify\n", "Type=simple\n")
m("unit: no reload", SV, "ExecReload=/bin/kill -HUP $MAINPID\n", "")
m("unit: executable path not escaped", SV, '    exe = exe.replace("%", "%%")                # systemd specifiers\n', "")
m("notify: abstract sockets not understood", "src/dizzy_store/sdnotify.py", '    if address.startswith("@"):                 # an abstract socket\n        address = "\\0" + address[1:]\n', "")

# ── updating
m("fingerprint: schema changes are not noticed", "src/dizzy_store/fingerprint.py", "    files = [Path(models.__file__), Path(events.__file__), Path(storeutil.__file__)]", "    files = [Path(events.__file__), Path(storeutil.__file__)]")
m("fingerprint: projections are not part of it", "src/dizzy_store/fingerprint.py", '    files += sorted((_kit.LIB / "projection").glob("*/src/*.py"))\n', "")
m("update: no rebuild when the fingerprint differs", ND, "        stale = not brand_new and stored != self.fingerprint", "        stale = False")
m("update: a brand-new store is rebuilt for nothing", ND, "        brand_new = stored is None and len(self.store) == 0", "        brand_new = False")
m("update: stale tables are patched, not dropped", ND, "        if stale:\n            pool_models.metadata.drop_all(self.sqla)", "        if False:\n            pass")
m("update: tables are indexed before the fingerprint is read", ND, "        ensure_state_table(self.sqla)\n        stored = read_flag(self.sqla, FINGERPRINT)", "        ensure_schema_extras(self.sqla)\n        stored = read_flag(self.sqla, FINGERPRINT)")
m("update: restart before reinstall", TL, '    plan.append(("reinstall the tool from the checkout",', '    plan.insert(0, ("reinstall the tool from the checkout",')
m("update: pull over uncommitted changes", TL, '        if _git(repo, "status", "--porcelain", "--untracked-files=no", runner=runner):', "        if False:")
m("update: a failed step does not stop it", TL, "            return result.returncode or 1", "            continue")

# ── the disk probe
m("doctor: FAT is acceptable", DC, '    "vfat": ("fail",', '    "vfat": ("ok",')
m("doctor: a read-only mount passes", DC, '    if m and "ro" in m.options.split(","):', "    if False:")
m("doctor: an unwritable root passes", DC, '    except PermissionError:\n        report.add("fail", "writable"', '    except ZeroDivisionError:\n        report.add("fail", "writable"')
m("doctor: corrupted read-back passes", DC, "        if hashlib.sha256(a.read_bytes()).digest() != hashlib.sha256(data).digest():", "        if False:")
m("doctor: ignored permissions pass", DC, "        if mode == 0o600:\n            report.add(\"ok\", \"permissions\"", "        if True:\n            report.add(\"ok\", \"permissions\"")
m("doctor: a shared OS filesystem passes", DC, "    shares_os = volumes.same_filesystem(real, \"/\")", "    shares_os = False")
m("doctor: the floor is not checked against space", DC, "    if min_free and avail <= min_free:", "    if False:")
m("doctor: the bench ignores room", DC, "                if avail - bench_bytes < max(256 * MiB, bench_bytes // 10, min_free or 0):", "                if False:")
m("doctor: scratch is left behind", DC, "            shutil.rmtree(work, ignore_errors=True)\n    if smart", "            pass\n    if smart")
m("doctor: the cliff threshold is too lax", DC, "    return (head, tail) if tail < 0.5 * head else None", "    return (head, tail) if tail < 0.05 * head else None")
m("doctor: one slow window counts as a collapse", DC, "    tail = statistics.median(rates[-quarter:])", "    tail = min(rates[-quarter:])")
m("doctor: a USB2 link is fine", DC, "        if disk.usb_mbps and disk.usb_mbps <= 480:", "        if False:")
m("doctor: encryption is never detected", VO, '            if uuid.startswith("CRYPT-"):\n                out.encrypted = True', '            if False:\n                out.encrypted = True')
m("volumes: mount escapes are not decoded", VO, "    return _OCTAL.sub(lambda m: chr(int(m.group(1), 8)), text)", "    return text")
m("volumes: the shallowest mount wins", VO, "        if inside and (best is None or len(m.mountpoint) >= len(best.mountpoint)):", "        if inside and best is None:")
m("eject: unmounts without syncing", EJ, '        say("-> sync")\n        sync()', '        say("-> sync")')
m("eject: ejects the system filesystem", EJ, '    if mount.mountpoint == "/" or volumes.same_filesystem(root, "/"):', "    if False:")
m("eject: ejects internal disks", EJ, "    if not mount.source.startswith(\"/dev/\") or not removable:", "    if False:")
m("eject: powers off a disk that would not unmount", EJ, '    if result.returncode != 0:\n        say(f"error: could not unmount', '    if False:\n        say(f"error: could not unmount')
m("eject: busy mounts name no one", EJ, "        for pid, cmd, how in holders(mount.mountpoint, proc):", "        for pid, cmd, how in []:")
m("eject: the daemon is not stopped first", EJ, '            result = do("stop the device", ["systemctl", "--user", "stop", unit])', '            result = subprocess.CompletedProcess([], 0, "", "")')

# ── transport (slower: real HTTP / daemons)
SRC = "src/dizzy_store/"
m("http: verify endpoint skips the is_hash guard", SRC + "peer_http.py", '    def verify(blob_hash: str):\n        if not is_hash(blob_hash):\n            raise HTTPException(400, "not a sha256")\n', "    def verify(blob_hash: str):\n", HTTP)
m("http: peer API accepts any token", SRC + "peer_http.py", '        if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], token)):\n            raise HTTPException(401, "bad or missing peer token")', "        pass", HTTP)
m("http: byte range end exclusive", SRC + "peer_http.py", "    end = min(end, size - 1)", "    end = min(end, size - 1) - 1", HTTP)
m("http: 503 treated as an answer", SRC + "peer_http.py", "            if response.status_code in (502, 503, 504):", "            if False:", HTTP)
m("http: verify never reaches the peer", SRC + "peer_http.py", '        response = self._send(peer_id, "GET", f"/peer/blob/{blob_hash}/verify",', '        response = self._send(peer_id, "GET", f"/peer/blob/{blob_hash}/stat",', HTTP)
m("daemon: catch-up before announce skipped", SRC + "daemon.py", "        self.catch_up()\n        self.announce()", "        self.announce()", HTTP)
m("antientropy: bucket digests never differ", SRC + "antientropy.py", '    return {prefix: hashlib.sha256("\\n".join(sorted(members)).encode()).hexdigest()\n            for prefix, members in buckets.items()}', '    return {prefix: "same" for prefix in buckets}', HTTP)
m("antientropy: only the first batch fetched", SRC + "antientropy.py", "    for start in range(0, len(missing), batch):", "    for start in range(0, min(len(missing), batch), batch):", HTTP)

# ── a portable drive: store discovery, "init means here", host-scoped memory, the one-daemon lock
LK = "src/dizzy_store/lock.py"
DR = "src/dizzy_store/drives.py"
m("here: only the directory itself is a store, never a parent of it", CFG, "    for directory in (cwd, *cwd.parents):", "    for directory in (cwd,):")
m("here: a drive's dizzy-store folder is not found from beside it", CFG, "    return child if (child / \".store\" / \"device.json\").is_file() else None", "    return None")
m("here: a configured default outranks the store you stand in", CFG, "    if here := store_from_here(cwd):\n        return by_root(here)\n    if cfg.default_device:\n        return by_name(cfg.default_device)", "    if cfg.default_device:\n        return by_name(cfg.default_device)\n    if here := store_from_here(cwd):\n        return by_root(here)")
m("here: init ignores where you stand", CL, "            if args.command == \"init\" and not _names_a_store(args):", "            if False:")
m("here: init ignores the environment's choice", CL, "    return bool(args.root or args.device or env.get(\"DIZZY_STORE_ROOT\") or env.get(\"STORE_ROOT\")\n                or env.get(\"DIZZY_STORE_DEVICE\"))", "    return bool(args.root or args.device)")
m("drives: the system volume and network mounts are scanned", DR, "        if mount.mountpoint == \"/\" or not mount.source.startswith(\"/dev/\"):\n            continue", "        if False:\n            continue")
m("drives: a drive dedicated to the store is not found", DR, "        for candidate in (top / STORE_DIRNAME, top):", "        for candidate in (top / STORE_DIRNAME,):")
m("drives: one store is listed once per mount of it", DR, "            if candidate in seen or not isinstance(data, dict):\n                continue", "            if not isinstance(data, dict):\n                continue")
m("drives: a garbled device file is fatal", DR, "            except (OSError, ValueError):\n                continue", "            except OSError:\n                continue")
m("drives: the list is in mount order", DR, "    return sorted(found, key=lambda f: (f.node_id, str(f.root)))", "    return found")
m("drives: two drives with one name: the first is chosen", CFG, "            if len(carrying) == 1:", "            if carrying:")
m("host: every computer shares one memory", DV, "    return os.environ.get(\"DIZZY_STORE_HOST\") or socket.gethostname()", "    return \"any\"")
m("host: the drive's memory of this computer beats this computer's config", DV, "            return s.listen or h.get(\"listen\") or d[\"listen\"]", "            return h.get(\"listen\") or s.listen or d[\"listen\"]")
m("host: seeds learned on one computer are used on all", DV, "            return {**d[\"seeds\"], **h.get(\"seeds\", {}), **(s.seeds or {})}", "            return {**d[\"seeds\"], **{k: v for hh in d.get(\"hosts\", {}).values() for k, v in hh.get(\"seeds\", {}).items()}, **(s.seeds or {})}")
m("host: the memory of this computer is ignored", DV, "            return s.listen or h.get(\"listen\") or d[\"listen\"]", "            return s.listen or d[\"listen\"]")
m("host: join writes the route for every computer", CL, "    device.remember_seed(info[\"node_id\"], args.url.rstrip(\"/\"))", "    device.data[\"seeds\"][info[\"node_id\"]] = args.url.rstrip(\"/\")", ["tests/test_idle.py::test_a_route_learned_by_join_belongs_to_the_computer_that_learned_it"])
m("site: this machine's site is ignored", DV, "            return s.site or d[\"site\"]", "            return d[\"site\"]")
m("site: the card announces the drive's own site", DV, "\"site\": self[\"site\"], \"location_note\": self[\"location_note\"]", "\"site\": d[\"site\"], \"location_note\": d.get(\"location_note\")")
m("lock: two holders at once", LK, "fcntl.LOCK_EX | fcntl.LOCK_NB", "fcntl.LOCK_SH | fcntl.LOCK_NB")
m("lock: the holder is not named", LK, "        os.write(fd, f\"{os.getpid()}\\n\".encode())\n", "")
m("lock: never released", LK, "            os.close(self._fd)\n            self._fd = None", "            self._fd = None")
m("lock: the loop acts before it is listening", DM, "            while not self.listening.wait(0.1):", "            while False:")
m("lock: a port that cannot be bound is an ordinary failure", DM, "        daemon.exit_code = EX_CONFIG\n    finally:", "        daemon.exit_code = 1\n    finally:")

# ── `run --until-idle`: it may say "up to date" only when that is true
m("idle: any answering peer counts as in step", DM, "            (self.in_step.add if theirs == ours else self.in_step.discard)(peer)", "            self.in_step.add(peer)", IDLE)
m("idle: a peer that stops answering still counts", DM, "                except PeerUnreachable:\n                    self.reached.discard(peer)\n                    self.in_step.discard(peer)\n                    continue", "                except PeerUnreachable:\n                    continue", IDLE)
m("idle: a peer is never counted as reached", DM, "            self.reached.add(peer)\n", "            pass\n", IDLE)
m("idle: being in step is not required", DM, "        if quiet >= policy.settle_s and in_step:", "        if quiet >= policy.settle_s:", IDLE)
m("idle: blobs still wanted do not matter", DM, "            if wanted == 0:\n                return done(0,", "            if True:\n                return done(0,", IDLE)
m("idle: gives up on blobs that are merely slow", DM, "            if backing_off == wanted:", "            if True:", IDLE)
m("idle: backing off is counted after the wait is over", DM, "backing_off += retry_after is not None and now < retry_after", "backing_off += retry_after is not None and now > retry_after", IDLE)
m("idle: the grace period is not waited out", DM, "            if now - started > policy.grace_s:", "            if now - started < policy.grace_s:", IDLE)
m("idle: no peer is never reported", DM, "        if not daemon.reached:", "        if False:", IDLE)
m("idle: no overall ceiling", DM, "        if policy.max_s is not None and now - started > policy.max_s:", "        if False:", IDLE)
m("idle: a stalled peer is waited for forever", DM, "        if quiet >= policy.stall_s and not in_step:", "        if False:", IDLE)
m("idle: the stall verdict comes at once", DM, "        if quiet >= policy.stall_s and not in_step:", "        if not in_step:", IDLE)
m("idle: activity does not restart the quiet clock", DM, "        if snapshot != last:\n            last, quiet_since = snapshot, now", "        if last is None:\n            last, quiet_since = snapshot, now", IDLE)
m("idle: judged before the listener is up", DM, "        if not daemon.listening.is_set() or daemon.passes < 1 or now - last_look < 1.0:", "        if daemon.passes < 1 or now - last_look < 1.0:", IDLE)
m("idle: judged before the first full pass", DM, "        if not daemon.listening.is_set() or daemon.passes < 1 or now - last_look < 1.0:", "        if not daemon.listening.is_set() or now - last_look < 1.0:", IDLE)
m("idle: progress is never reported", DM, "            say(f\"  {held:,} blobs held, {wanted:,} still wanted…\")", "            pass", IDLE)
m("idle: a surprise ends the watch", DM, "        except Exception:                                # a surprise must not leave a person waiting forever\n            log.exception(\"until-idle: could not look at the device\")\n            continue", "        except OSError:\n            continue", IDLE)
m("idle: the device does not speed up", DM, "        daemon.fast = 1.0", "        daemon.fast = None", IDLE)
m("idle: the verdict is not the exit status", DM, "        return daemon.idle_result[0]\n", "        return 0\n", IDLE)
m("idle: --eject runs after a run that did not finish", CL, "    if args.eject and code == 0:", "    if args.eject:", IDLE)
JOIN = ["tests/test_join.py"]
m("join: a store of another cluster is re-labelled", CL, "    if mine and mine != theirs:", "    if False:", JOIN)
m("join: rejoining your own cluster is refused", CL, "    if mine and mine != theirs:", "    if mine:", JOIN)
PULLREQ = ["tests/test_pull_requests.py"]
m("pull-request: a knock from another cluster is serviced", ND, "        if not mine or theirs != mine:", "        if False:", PULLREQ)
m("pull-request: a knock from a device with no cluster is serviced", ND, "        if not mine or theirs != mine:", "        if mine and theirs and theirs != mine:", PULLREQ)
m("pull-request: every knock is refused", ND, "        if not mine or theirs != mine:", "        if True:", PULLREQ)
m("pull-request: a refusal is not reported", ND, "            self._on_progress(Progress(stage=\"pull_refused\", detail=f\"{requester} asked to be pulled from, but {why}\"))", "            pass", PULLREQ)
m("pull-request: a refused knock leaves its address behind", ND, "                self.peers.forget(requester)           # its address hint must not outlive its welcome", "                pass", PULLREQ)
m("pull-request: forget leaves the hint", SRC + "peer_http.py", "        self._hints.pop(peer_id, None)\n        self._last_good.pop(peer_id, None)", "        self._last_good.pop(peer_id, None)", PULLREQ)
m("pull-request: forget leaves the last good address", SRC + "peer_http.py", "        self._hints.pop(peer_id, None)\n        self._last_good.pop(peer_id, None)", "        self._hints.pop(peer_id, None)", PULLREQ)
m("pull-request: a vanished knocker is an error", ND, "                    except PeerUnreachable:\n                        pass                           # the requester went away again", "                    except ZeroDivisionError:\n                        pass", PULLREQ)
m("service: a virtualenv executable is not called out", SV, '    if ".venv" in parts or "venv" in parts:', '    if False:')
m("service: install does not show the warning", CL, '    warning = service.exe_warning(exe)\n    if warning:\n        print(warning, file=sys.stderr)', '    pass')
m("idle: --eject is not checked up front", CL, "        if run_eject(root, None, dry_run=True, power_off=False, say=why.append) != 0:", "        if False:", IDLE)
m("idle: a peer is talked to without the daemon lock", DM, "            with self.lock:         # the peers client looks the peer's address up in the node's read models, and a\n                try:                # SQLAlchemy session is not thread-safe: never beside the tick, as sync_peer is not\n", "            if True:\n                try:\n", IDLE)
m("idle: the eject goes ahead while the loop is still busy", CL, "        elif args.eject and code == 0:", "        elif False:", IDLE)
m("idle: the store is closed while the loop is still busy", CL, "        if daemon.loop_done:\n            with contextlib.suppress(Exception):", "        if True:\n            with contextlib.suppress(Exception):", IDLE)
m("idle: a loop that never stopped is not noticed", DM, "        daemon.loop_done = not loop.is_alive()", "        daemon.loop_done = True", IDLE)



SLOTS: "queue.Queue[int]" = queue.Queue()
SCRATCH: Path


def make_slot(slot: int) -> None:
    root = SCRATCH / f"slot{slot}"
    shutil.copytree(STORE, root / "store", symlinks=True, ignore=shutil.ignore_patterns(
        ".venv", "__pycache__", ".pytest_cache", "*.pyc", "*.orig"))
    for name in ("host", "ext", "dagstore"):
        if (REPO / name).exists():
            (root / name).symlink_to(REPO / name)


def run_one(item):
    slot = SLOTS.get()                                      # a scratch tree no one else is editing
    try:
        return _run_one(slot, item)
    finally:
        SLOTS.put(slot)


def _run_one(slot, item):
    label, rel, old, new, tests = item
    root = SCRATCH / f"slot{slot}" / "store"
    path = root / rel
    src = path.read_text()
    if src.count(old) != 1:
        return label, "UNAPPLIABLE", f"{src.count(old)} matches"
    bak = path.with_suffix(path.suffix + ".orig")
    shutil.copy(path, bak)
    try:
        path.write_text(src.replace(old, new, 1))
        try:
            r = subprocess.run([PY, "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider"],
                               cwd=root, capture_output=True, text=True, timeout=300,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        except subprocess.TimeoutExpired:
            return label, "CAUGHT", "(timed out)"          # a mutation that hangs the suite is caught
        why = next((l for l in r.stdout.splitlines() if l.startswith("FAILED")), "")
        if r.returncode != 0 and not why:               # died without a failing test: say how (an ERROR, a crash…)
            tail = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()][-3:]
            why = "(no FAILED line) " + " | ".join(tail)
        return label, "CAUGHT" if r.returncode != 0 else "SURVIVED", why[:300]
    finally:
        shutil.move(bak, path)


def main() -> int:
    global SCRATCH
    jobs = int(os.environ.get("JOBS", "4"))
    only = sys.argv[1:]
    items = [it for it in M if not only or any(o in it[0] for o in only)]
    SCRATCH = Path(tempfile.mkdtemp(prefix="store-mut-"))
    try:
        for j in range(jobs):
            make_slot(j)
            SLOTS.put(j)
        results = []
        with ThreadPoolExecutor(jobs) as pool:
            for label, status, why in pool.map(run_one, items):
                print(f"{status:10s} {label}" + (f"   <- {why}" if why and status != "SURVIVED" else ""), flush=True)
                results.append((label, status))
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    bad = [(l, s) for l, s in results if s != "CAUGHT"]
    print(f"\n{len(results) - len(bad)}/{len(results)} caught")
    for label, status in bad:
        print(f"  {status}: {label}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
