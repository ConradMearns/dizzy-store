# Writing a store scenario

A scenario is a **data file** that proves one behavior of the storage replicator
across a *cluster of devices*. No Python. It extends the logger's format
(`scenarios/AUTHORING.md` at the repo root: `command` / `event` / `claim` steps)
with the steps a cluster needs. Runner: `store/tests/test_scenarios.py`
(`uv run --project store pytest store/tests/test_scenarios.py -k evict`).

```
scenarios/<kebab-case-behavior>/
  about.md         # 3-6 lines: what it proves, tags, provenance
  scenario.yaml    # the ordered step stream
```

Devices are REAL (real procedures, projections, queries, policies, DAG
replication); only the **network** and the **clock** are simulated. Every scenario
also runs over REAL HTTP on localhost (`tests/test_scenarios_http.py`) — if one
passes in simulation but fails there, the two transports disagree. Time is
frozen at `2026-01-01T00:00:00` and moves only on `advance`. After every step the
cluster runs to idle, then the **invariants** are checked (below).

> YAML 1.1 reads `on`, `yes`, `no` as booleans — which is why the device key is
> `at:`, not `on:`. Quote strings that look like other scalars.

## Steps (a YAML list; one kind of step each)

| step | meaning |
|---|---|
| `cluster: {name: {…}}` | Declare devices. The first founds the cluster; all announce. Keys: card — `role` (hot/archive/cold), `site`, `wants`, `location_note`, `draining`, `endpoints`; config — any `env.store` field (`limit_bytes: 10KB`, `max_dispatch_per_event`, `live_window_s`, `high_watermark`…). The filesystem under a device can be simulated: `disk_capacity: 20KB` gives it a disk that size and `disk_other: 4KB` puts someone else's data on it, so `min_free_bytes: 6KB` (the free-space floor) can be tested without filling a real one. `min_evict_bytes: 2KB` exempts
blobs under 2KB from eviction under pressure (not from a drain). Devices do **not** know each other until they `sync`. |
| `{at: dev, command: name, fields: {…}}` | Dispatch a command on a device. `occurred_at` defaults to now. `expect: rejects` asserts it refuses. |
| `{at: dev, upload: name, size: 4KB, collection: photos}` | The edge's job: write deterministic bytes under the device's root, then `put_blob`. `chunk_size: 1KB` records a chunk recipe. `upload: "p-{n}"` + `count: 12` makes many. `$name` then refers to the blob's sha256. |
| `tree: {at: dev, dir: books, files: {a.txt: 3KB}}` | Lay plain files on disk (for `adopt_collection`); blobs are `$books/a.txt`, the directory is `$path:books`. `layout: cas` names the files by their hash (the logger's `cas/`); `truncate: [a.bin]` leaves a file holding half the bytes its name claims; `stray: [a.txt]` leaves half a file already at the device's blob address. |
| `edit: {at: dev, dir: books, file: a.txt}` | Overwrite the first byte of a tree file IN PLACE (an editor saving over it); `unreadable: true` makes it unopenable instead. If the device's blob shared those bytes (a `link: true` adoption) the invariants are told it is damaged. |
| `sync: all` / `{node: a, peer: b, direction: both}` | Run `sync_peer`. `all` = every online device syncs with every other. |
| `net: {offline: dev}` / `{online: dev}` / `{partition: [[a,b],[b,c]]}` / `{heal: true}` | The network. Offline devices cannot run commands or be reached; their work waits. A partition lists groups; two devices talk iff some group holds both. |
| `advance: 2h` | Move the clock (`30s`, `10m`, `2h`, `3d`). A leading minus moves it BACK — a replaced drive's dead clock: `advance: -10d`. |
| `sweep: dev` / `all` | One paced catch-up tick (the product's own `sweep`). |
| `announce: dev` / `{node: dev, draining: true}` | Re-announce the card, with overrides. |
| `wipe: dev` | The disk was replaced: all bytes and facts gone, a NEW epoch. |
| `fault: {at: dev, corrupt: $x}` / `{… remove: $x}` / `{… unreadable: $x}` | Damage a copy on disk (data loss by design — unless another device holds it). `corrupt` flips the first byte; `every: 1KB` flips one byte in every 1 KB block (every chunk of a chunked file). |
| `claim: {at: dev, …}` | Check something — see below. |

A first step `- time: 2026-09-30T12:00:00` sets the start instant.

## Claims

Queries only (the feat's `queries:`), as in the logger — plus the blob API:

```yaml
- claim: {at: laptop, blob: $photo-1, has: true}     # bytes are there AND match the hash
- claim:
    at: server
    query: get_blob_replicas
    input: {blob_hash: $photo-1}
    expect:
      count: 2
      contains: [{node_ids: laptop, states: present}]
```
Modes: `contains` / `not_contains` (column-wise rows) · `count` · `empty` ·
`equals: {field: value}`. Outputs are parallel lists (`node_ids`, `states`, …)
except scalar queries (`get_collection_policy`, `get_peer_link`…) — use `equals`.

## Invariants — free, after every step

`claims-match-bytes` (the log never lies about the disk, unless a fault was
injected — and a repaired fault stops being exempt) · `never-last-copy` (nothing
the system does destroys the last verified copy; damaging or wiping the SOLE
holder is excused) · `small-blobs-stay` (nothing smaller than a node's `min_evict_bytes` is ever
evicted under pressure — a drain is exempt) · `models-converge` (equal event heads ⇒ equal read models).
After the LAST step, once: `confluent-folds` (the same events folded in two
different valid orders give identical read models). They are
`dizzy_store/invariants.py`; add one there and every existing scenario is checked
against it.

## Rules of thumb

- One behavior per scenario; name the folder after the behavior.
- Facts a device issues about a subject it already spoke of are stamped strictly
  after its previous one, so scenarios need not `advance` between a device's own
  re-announcements.
- A step that should not happen is claimed *not to have*: eviction refused → the
  bytes are still there.
- A scenario must isolate its guard. Several rules overlap (a node that wants a
  collection is also protected by its role), so a claim that "eviction was refused"
  can pass for the wrong reason: give the node a card where ONLY the rule under
  test applies (an archive that wants nothing; a cold drive that is draining).
- **Every surprise becomes a scenario** — and every safety rule should be
  *mutation-tested*: break it in the product code and confirm a scenario goes red
  (that is how `log-claims-are-not-trusted-for-eviction` and
  `same-size-rot-does-not-anchor-eviction` were found). What scenarios cannot see
  — what a failure records, which peer is asked first, quarantine contents, fold
  order — has unit tests beside them in `store/tests/`.
