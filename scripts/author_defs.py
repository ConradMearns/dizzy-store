"""Author store/def/* (the LinkML schemas) from a compact field spec + the feat's own descriptions.

    python store/scripts/author_defs.py        # then: store/scripts/regen.sh does this AND the types

The spec below is the one place a field's name, type and optionality are written down; the prose
comes from store.feat.yaml, so the contract and the schemas cannot drift in meaning. Run it after any
change to the feat that adds or removes a field, then regenerate gen_def/gen_int (regen.sh)."""
import os
from pathlib import Path
import yaml

ROOT = Path(os.environ.get("STORE_DIR", Path(__file__).resolve().parents[1]))
feat = yaml.safe_load((ROOT / "store.feat.yaml").read_text())
norm = lambda t: " ".join(str(t).split())

S, I, B, D, F = "string", "integer", "boolean", "datetime", "float"

def attrs(fields):
    out = {}
    for f in fields:
        name, rng, req = f[0], f[1], f[2]
        desc = f[3] if len(f) > 3 else None
        multi = f[4] if len(f) > 4 else False
        a = {"range": rng, "required": bool(req)}
        if multi:
            a["multivalued"] = True
        if desc:
            a["description"] = desc
        out[name] = a
    return out

HEADER = lambda id_, name, desc=None: {
    "id": f"https://example.org/{id_}", "name": name,
    **({"description": norm(desc)} if desc else {}),
    "prefixes": {"linkml": "https://w3id.org/linkml/"},
    "default_range": "string", "imports": ["linkml:types"]}

def dump(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(doc, sort_keys=False, width=10**6,
                              default_flow_style=None, allow_unicode=True))

# ── commands ─────────────────────────────────────────────────────────────────
OCC = ("occurred_at", D, 1)
COMMANDS = {
 "create_cluster": [("cluster_id", S, 1), OCC],
 "announce_node": [("role", S, 1, "'hot' | 'archive' | 'cold'"), ("site", S, 1),
   ("location_note", S, 0), ("endpoints", S, 0, "urls peers can reach this node at", True),
   ("wants", S, 0, "collections wanted in full, or ['*']", True),
   ("draining", B, 0, "being retired; absent means false"), OCC],
 "set_collection_policy": [("collection", S, 1), ("min_sites", I, 1),
   ("verify_max_age_days", I, 1), ("evictable", B, 1), OCC],
 "put_blob": [("blob_hash", S, 1, "sha256 hex"), ("byte_size", I, 1), ("collection", S, 1),
   ("chunk_size", I, 0, "large files only"),
   ("chunk_hashes", S, 0, "ordered chunk sha256 hexes; large files only", True), OCC],
 "adopt_collection": [("collection", S, 1), ("root", S, 1),
   ("layout", S, 1, "'cas' | 'tree'"),
   ("link", B, 0, "hard-link instead of copy (same filesystem; for trees nothing edits in place)"), OCC],
 "replicate_blob": [("blob_hash", S, 1), ("from_node", S, 0),
   ("reason", S, 1, "'replica' | 'backfill' | 'read_through'"), OCC],
 "evict_blob": [("blob_hash", S, 1), ("reason", S, 1, "'pressure' | 'drain'"), OCC],
 "set_blob_pin": [("blob_hash", S, 1), ("pinned", B, 1), ("reason", S, 0), OCC],
 "record_blob_access": [
   ("blob_hashes", S, 1, "parallel with last_access_ats", True),
   ("last_access_ats", D, 1, None, True), OCC],
 "check_capacity": [OCC],
 "sync_peer": [("peer_id", S, 1), ("direction", S, 1, "'pull' | 'push' | 'both'"), OCC],
 "scrub_blobs": [("collection", S, 0), ("max_bytes", I, 1), OCC],
}
assert set(COMMANDS) == set(feat["commands"]), set(COMMANDS) ^ set(feat["commands"])
doc = HEADER("commands", "commands")
doc["classes"] = {n: {"description": norm(feat["commands"][n]), "attributes": attrs(f)}
                  for n, f in COMMANDS.items()}
dump(ROOT / "def/commands.yaml", doc)

# ── events ───────────────────────────────────────────────────────────────────
NODE, EPOCH, HASH = ("node_id", S, 1), ("epoch", S, 1), ("blob_hash", S, 1)
EVENTS = {
 "cluster_created": [("cluster_id", S, 1), ("created_by", S, 1), OCC],
 "node_announced": [NODE, ("cluster_id", S, 1), EPOCH, ("role", S, 1), ("site", S, 1),
   ("location_note", S, 0), ("endpoints", S, 0, None, True), ("wants", S, 0, None, True),
   ("draining", B, 0), OCC],
 "collection_policy_set": [("collection", S, 1), ("min_sites", I, 1),
   ("verify_max_age_days", I, 1), ("evictable", B, 1), OCC],
 "blob_registered": [HASH, ("byte_size", I, 1), ("collection", S, 1),
   ("chunk_size", I, 0), ("chunk_hashes", S, 0, None, True), OCC],
 "blob_stored": [NODE, EPOCH, HASH,
   ("source", S, 1, "'upload' | 'adopted' | 'replica' | 'backfill' | 'read_through'"), OCC],
 "blob_evicted": [NODE, EPOCH, HASH, ("reason", S, 1), ("confirmed_sites", I, 1), OCC],
 "blob_pin_set": [NODE, EPOCH, HASH, ("pinned", B, 1), ("reason", S, 0), OCC],
 "blob_access_recorded": [NODE, EPOCH, ("blob_hashes", S, 1, None, True),
   ("last_access_ats", D, 1, None, True), OCC],
 "blob_corrupt": [NODE, EPOCH, HASH, ("found_hash", S, 0), OCC],
 "blob_replication_failed": [NODE, HASH, ("from_node", S, 0),
   ("reason", S, 1, "'not_held' | 'hash_mismatch' | 'out_of_space'"), OCC],
 "space_pressure_detected": [NODE, ("used_bytes", I, 1), ("limit_bytes", I, 1),
   ("free_bytes", I, 0, "the filesystem's room left when it was read"),
   ("bytes_to_free", I, 1), OCC],
 "scrub_completed": [NODE, EPOCH, ("collection", S, 0), ("checked", I, 1), ("corrupt", I, 1),
   ("bytes_checked", I, 1), ("cursor", S, 0), ("pass_complete", B, 1),
   ("pass_started_at", D, 0), OCC],
 "peer_link_changed": [NODE, ("peer_id", S, 1), ("healthy", B, 1), ("reason", S, 0), OCC],
}
assert set(EVENTS) == set(feat["events"]), set(EVENTS) ^ set(feat["events"])
doc = HEADER("events", "events")
doc["classes"] = {n: {"description": norm(feat["events"][n]), "attributes": attrs(f)}
                  for n, f in EVENTS.items()}
dump(ROOT / "def/events.yaml", doc)

# ── queries ──────────────────────────────────────────────────────────────────
def L(name, rng=S, desc=None):           # a parallel-list output column
    return (name, rng, 0, desc, True)
QUERIES = {
 "get_node_profile": ([("node_id", S, 1)],
   [("found", B, 1), ("node_id", S, 0), ("cluster_id", S, 0), ("epoch", S, 0),
    ("role", S, 0), ("site", S, 0), ("location_note", S, 0),
    ("endpoints", S, 0, None, True), ("wants", S, 0, None, True), ("draining", B, 0),
    ("announced_at", S, 0, "ISO 8601")]),
 "get_node_usage": ([("node_id", S, 1)],
   [("held_count", I, 1), ("held_bytes", I, 1)]),
 "list_peers": ([("node_id", S, 1, "the node to exclude (this one)")],
   [L("node_ids"), L("cluster_ids"), L("epochs"), L("roles"), L("sites"),
    L("location_notes"), L("endpoints_jsons", S, "JSON list per node"),
    L("wants_jsons", S, "JSON list per node"), L("drainings", B)]),
 "get_collection_policy": ([("collection", S, 1)],
   [("collection", S, 1), ("min_sites", I, 1), ("verify_max_age_days", I, 1),
    ("evictable", B, 1), ("declared", B, 1, "false when these are the defaults"),
    ("declared_at", S, 0, "ISO 8601; empty when undeclared")]),
 "get_blob": ([HASH],
   [("found", B, 1), ("blob_hash", S, 0), ("byte_size", I, 0), ("collection", S, 0),
    ("first_seen_at", S, 0, "ISO 8601"), ("chunk_size", I, 0),
    ("chunk_hashes", S, 0, None, True)]),
 "get_blob_replicas": ([HASH],
   [L("node_ids"), L("epochs"), L("states"), L("pinneds", B), L("stored_ats", S, "ISO 8601"),
    L("last_access_ats", S, "ISO 8601, empty when never read"), L("roles"), L("sites"),
    L("drainings", B), L("verified_ats", S, "ISO 8601 — stored, or the last full scrub pass if later")]),
 "get_missing_blobs": ([("node_id", S, 1), ("limit", I, 0),
   ("order", S, 0, "'newest' (default) | 'smallest'")],
   [L("blob_hashes"), L("byte_sizes", I), L("collections")]),
 "get_eviction_candidates": ([("node_id", S, 1), ("bytes_needed", I, 0), ("limit", I, 0)],
   [L("blob_hashes"), L("byte_sizes", I), L("collections")]),
 "get_at_risk_blobs": ([("limit", I, 0), ("collection", S, 0)],
   [L("blob_hashes"), L("byte_sizes", I), L("collections"),
    L("first_seen_ats", S, "ISO 8601"), L("sites_holding", I), L("sites_needed", I)]),
 "get_drain_remaining": ([("node_id", S, 1)],
   [("held_count", I, 1), ("held_bytes", I, 1),
    ("unsafe_count", I, 1, "held blobs not yet safe elsewhere")]),
 "get_blobs_held": ([("node_id", S, 1), ("collection", S, 0), ("limit", I, 0)],
   [L("blob_hashes"), L("byte_sizes", I), L("collections"),
    ("pass_started_at", S, 0, "ISO 8601; empty when no pass is in progress")]),
 "get_peer_link": ([("node_id", S, 1), ("peer_id", S, 1)],
   [("known", B, 1), ("healthy", B, 1), ("changed_at", S, 0, "ISO 8601")]),
}
assert set(QUERIES) == set(feat["queries"]), set(QUERIES) ^ set(feat["queries"])
camel = lambda n: "".join(w.capitalize() for w in n.split("_"))
for n, (ins, outs) in QUERIES.items():
    doc = HEADER(f"queries/{n}", n, feat["queries"][n]["description"])
    doc["classes"] = {
        f"{camel(n)}Input": {"description": f"Input for {n}", "attributes": attrs(ins)},
        f"{camel(n)}Output": {"description": f"Output for {n}", "attributes": attrs(outs)}}
    dump(ROOT / f"def/queries/{n}.yaml", doc)

# ── models ───────────────────────────────────────────────────────────────────
def ident(name="id", desc=None):
    a = {"range": S, "required": True, "identifier": True}
    if desc: a["description"] = desc
    return {name: a}
MODEL = {
 "Node": ("One row per node_id: its latest public card (latest occurred_at wins).",
   {**ident("node_id"), **attrs([("cluster_id", S, 1), ("epoch", S, 1), ("role", S, 1),
    ("site", S, 1), ("location_note", S, 0), ("endpoints_json", S, 0, "JSON list"),
    ("wants_json", S, 0, "JSON list"), ("draining", B, 1), ("announced_at", D, 1),
    ("digest", S, 1, "payload digest — the last-writer-wins tie-break")])}),
 "CollectionPolicy": ("One row per collection: the latest declared policy.",
   {**ident("collection"), **attrs([("min_sites", I, 1), ("verify_max_age_days", I, 1),
    ("evictable", B, 1), ("declared_at", D, 1), ("digest", S, 1)])}),
 "Blob": ("One row per registered blob — what EXISTS, whoever holds it.",
   {**ident("blob_hash"), **attrs([("byte_size", I, 1), ("collection", S, 1),
    ("first_seen_at", D, 1), ("digest", S, 1, "payload digest of the earliest registration — the tie-break"),
    ("chunk_size", I, 0), ("chunk_hashes_json", S, 0, "JSON list; large files only"),
    ("chunk_at", D, 0, "when the earliest recipe was registered"),
    ("chunk_digest", S, 0, "payload digest of the earliest recipe")])}),
 "BlobLocation": ("One row per (blob, node, epoch): a node's claim to hold a blob in one life of it.",
   {**ident("id", "node_id|epoch|blob_hash"), **attrs([("blob_hash", S, 1), ("node_id", S, 1),
    ("epoch", S, 1), ("state", S, 1, "'present' | 'evicted' | 'corrupt'"), ("pinned", B, 1),
    ("stored_at", D, 0), ("last_access_at", D, 0)])}),
 "ScrubState": ("One row per (node, epoch, collection): where scrub resumes, and the last full pass.",
   {**ident("id", "node_id|epoch|collection ('' = all)"), **attrs([("node_id", S, 1),
    ("epoch", S, 1), ("collection", S, 1), ("cursor", S, 0),
    ("pass_started_at", D, 0), ("last_full_pass_at", D, 0)])}),
 "PeerLink": ("One row per (node, peer): the link state as that node last recorded it.",
   {**ident("id", "node_id|peer_id"), **attrs([("node_id", S, 1), ("peer_id", S, 1),
    ("healthy", B, 1), ("changed_at", D, 1), ("digest", S, 1)])}),
}
doc = HEADER("models/pool", "pool", feat["models"]["pool"]["description"])
doc["classes"] = {n: {"description": d, "attributes": a} for n, (d, a) in MODEL.items()}
dump(ROOT / "def/models/pool.yaml", doc)

# ── environment + telemetry ─────────────────────────────────────────────────
ENV = {
 "store": [("node_id", S, 1), ("cluster_id", S, 0), ("epoch", S, 1), ("root", S, 1),
   ("state_dir", S, 1), ("tmp_dir", S, 1), ("quarantine_dir", S, 1),
   ("limit_bytes", I, 1), ("high_watermark", F, 1), ("low_watermark", F, 1),
   ("live_window_s", I, 1), ("max_dispatch_per_event", I, 1),
   ("max_bytes_per_sec", I, 1),
   ("scrub_bytes_per_sec", I, 1), ("chunk_threshold_bytes", I, 1), ("chunk_size", I, 1),
   ("min_free_bytes", I, 0, "the filesystem must keep this much free; absent or 0 = off")],
 "disk": [("root", S, 0, "informational: the directory whose filesystem is measured")],
 "peers": [("seeds", S, 0, "bootstrap addresses for first contact", True)],
}
doc = HEADER("environment", "environment")
doc["classes"] = {n: {"description": norm(feat["environment"][n]), "attributes": attrs(f)}
                  for n, f in ENV.items()}
dump(ROOT / "def/environment.yaml", doc)
TEL = {
 "progress": [("stage", S, 1), ("detail", S, 1)],
 "transfer_progress": [("blob_hash", S, 1), ("peer_id", S, 1), ("bytes_done", I, 1),
   ("bytes_total", I, 1)],
 "peer_health": [("peer_id", S, 1), ("reachable", B, 1), ("latency_ms", I, 0), ("detail", S, 0)],
}
doc = HEADER("telemetry", "telemetry")
doc["classes"] = {n: {"description": norm(feat["telemetry"][n]), "attributes": attrs(f)}
                  for n, f in TEL.items()}
dump(ROOT / "def/telemetry.yaml", doc)
print("authored: commands", len(COMMANDS), "events", len(EVENTS), "queries", len(QUERIES),
      "model classes", len(MODEL), "env", len(ENV), "telemetry", len(TEL))
