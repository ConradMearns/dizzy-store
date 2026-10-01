# store — a personal cloud storage replicator (working title)

Hot devices keep what is recent, archive and cold devices keep the rest, and any
device fetches what it lacks from a peer. Design: `store.feat.yaml` (the
contract — principles, commands, events, queries, policies). A DIZZY feature:
`def/` (authored schemas) → `lib/python-uv/` (generated types + element
implementations) → `src/dizzy_store/` (runtime glue).

## Install

```sh
uv tool install --editable ./store        # puts `dizzy-store` on PATH, running live from this checkout
```

The install is **editable on purpose**: the command runs the code in the git checkout, so updating is
`dizzy-store update` (or `dizzy-store update --pull`, which does a `git pull --ff-only` first and refuses
over uncommitted changes). It reinstalls from the checkout and restarts running devices. What makes that
safe: a start that finds its read models were built by different code or a different schema rebuilds
them from the log (a few seconds, once); events only ever change by adding fields. `dizzy-store version`
says what is running.

## Configure

What a device **is** (its name, role, site, what it wants) is set by `init` and lives with its data in
`<root>/.store/`. How **this machine** finds and runs it lives in a layered config, like DIZZY's own:

    /etc/dizzy-store/config.yaml  <  ~/.config/dizzy-store/config.yaml  <  ./.dizzy-store.yaml
    <  $DIZZY_STORE_CONFIG  <  --config FILE  <  environment  <  flags

```yaml
# ~/.config/dizzy-store/config.yaml        (`dizzy-store config` prints the full template)
default_device: laptop
defaults:
  site: home              # where THIS computer is: every device run here announces it
devices:
  laptop:
    root: ~/.dizzy-store/laptop      # user-level: no root, nothing device-wide
    listen: 127.0.0.1:7701
    limit: 100GB          # the most this device may hold in blobs
    min_free: 20GB        # the filesystem must always keep this much free (the store is rarely the only writer)
```

A portable drive needs no entry here — see [A portable drive](#a-portable-drive).

A command finds its store the way git finds a repository: `--root` / `-d NAME`, then `$DIZZY_STORE_ROOT` /
`$DIZZY_STORE_DEVICE`, then the store you are standing in, then `default_device` (or the only device).
`dizzy-store config --show` prints what is in force and where each file was read. A relative `root:` is
relative to the file that says it, so a `.dizzy-store.yaml` next to a drive's data can say `root: .`.

## Run a device

```sh
dizzy-store -d laptop init --role archive --site home --wants '*'    # root, name and limit come from the config
dizzy-store -d laptop found                                          # the first device founds the cluster
dizzy-store -d laptop run                                            # by hand: peer API + admin API + tick loop

# on another device (same --peer-token, printed by `init`):
dizzy-store -d wd init --role cold --site shelf --wants '*' --peer-token …
dizzy-store -d wd join --url http://127.0.0.1:7702
```

Or without any config — a drive carries its own state, so: plug it in, `cd` into it, `dizzy-store init
--node-id wd --role cold --site shelf --limit-bytes 500GB`, `dizzy-store run`.

Against a running daemon: `status` · `put FILE… --collection photos` · `get HASH -o OUT` (read-through:
fetched back from a peer if evicted here) · `cmd NAME key=value…` · `query NAME key=value…` · `sweep` ·
`sync PEER` · `tick`. Peers reach each other over any private link — a Tailscale tailnet or an SSH tunnel
(`ssh -L`/`-R`); a card's endpoints are plain URLs. v0 authenticates peers with a shared bearer token;
the admin API has its own, local-only token.

### Several stores on one machine

A store is a root folder with its own event log and its own cluster, and a machine can run as many as you like
side by side — each its own device in the config (`devices:`), with its own `listen` port and its own
`systemctl --user enable dizzy-store@NAME`. Stores in different clusters never sync: give them different peer
tokens (the default) and a readable name with `found --cluster-id NAME`. `join` refuses a store that already
belongs to a cluster, so a slip cannot merge two logs. The number of stores is the number of *owners* whose data
must stay apart, not the number of disks: a root only has to sit on one filesystem (a pooled volume is one root),
and the event log is a small file inside it.

### Under systemd (your user, no root)

```sh
dizzy-store service install                         # writes ~/.config/systemd/user/dizzy-store@.service
systemctl --user enable --now dizzy-store@laptop    # the instance name is the device's name in the config
systemctl --user status dizzy-store@laptop          # journalctl --user -u dizzy-store@laptop -f
systemctl --user reload dizzy-store@laptop          # SIGHUP: re-read the config, apply it live
```

`Type=notify` (so `start` returns when the listener really answers), `Restart=on-failure` but **not on exit
78** (an unmounted drive or a wrong path — restarting cannot fix it). A reload applies limits, the
free-space floor, pacing, cadence, seeds and the announced card; a bad file is refused and the running
configuration kept; a changed `listen` or `root` waits for a restart and says so. `loginctl enable-linger`
lets it start at boot without a login.

### Drives

```sh
dizzy-store doctor /media/you/WD/dizzy-store                 # facts + capability checks (read-only except a scratch dir it removes)
dizzy-store doctor --bench 20GB                              # sustained writes, cold reads, hashing, small files
dizzy-store -d wd eject                                      # stop the device, sync, unmount, power off
```

`doctor` reads what the path lives on (filesystem, mount options, the disk — spinning or not, USB link
speed, encryption through LUKS/LVM, free space, whether it shares the OS volume) and exercises what the
store depends on (write+fsync+read-back, rename over an existing file, 0600 permissions, hard links,
unicode names, a directory of thousands of files). A large `--bench` shows a drive whose fast cache
fills (SMR) as a collapse in write speed. Each finding is ok / info / WARN / FAIL with the fix.

If the drive disappears while the daemon runs, the daemon **stops** (exit 74) rather than recreate its
paths: writing on would put blobs on the wrong disk and record them as stored. `init` refuses to make a
store under a removable-media path whose parent is on the system volume (an unmounted drive).

### A portable drive

A drive you carry between computers needs **no entry in any config**. What it *is* (name, role, limits,
tokens) lives on the drive; what differs from one computer to the next is settled where it is plugged in:

| differs per computer | how it is settled |
|---|---|
| where it is mounted | `dizzy-store drives` lists the stores on whatever is mounted; `-d NAME` finds one by its name; or just `cd` into it |
| its listen port, its route to peers | remembered **per computer** inside the drive (`hosts:` in `device.json`, keyed by hostname) — a tunnel address that works on the laptop does not follow the drive to the desktop |
| where it physically is (`site`, its failure domain) | this computer's `defaults: {site: …}` overrides the drive's own while it is here |

The routine:

```sh
udisksctl mount -b /dev/sdX1                         # if the computer does not automount it
dizzy-store -d wd run --until-idle --eject           # sync with the cluster, then unmount and power off
```

`--until-idle` finishes (exit 0) only when the drive holds **exactly the events a peer holds** — so the
cluster knows what the drive has, not just the drive what the cluster has — wants no blob it lacks, and
nothing has changed for a few seconds. It exits **75** (try again) when no peer answers, when a peer
answers but cannot reach back to pull the drive's events, or when the blobs it wants cannot be had; and it
says which. `--eject` happens only after a clean 0, and is checked up front (a store on the system disk is
refused before any syncing). `--wait SECONDS` bounds the run.

Each computer needs the tool (`uv tool install --editable ./store`), the same numeric user id (ext4 keeps
owners as numbers), and a route to a peer (a tailnet or a tunnel). One computer runs a drive at a time: a
lock on `<root>/.store/daemon.lock` refuses the second process, whoever starts it.

## Bring in what you already have

```sh
dizzy-store cmd adopt_collection collection=books root=/data/books layout=tree
dizzy-store cmd adopt_collection collection=legacy root=/srv/app/cas layout=cas link=true
```

Every new file is hashed on the way in — a `cas` file whose bytes do not match its
name is skipped and reported, never recorded — and by default **copied** into the
device's root, so the original can be edited or deleted freely. `link=true`
hard-links instead (same filesystem only): no extra space, which is what a nearly
full disk needs, but only for a tree nothing edits in place — the content address
makes a broken promise loud (scrub finds it, a peer repairs it). Re-running an
adoption costs a directory walk: names already held are not re-read. The run holds
the device's engine until it finishes (it is hashing, rate-limited by
`scrub_bytes_per_sec`), so a very large tree pauses that device's periodic jobs.

### A big tree behind a slow link

```sh
REMOTE=user@host:/path/to/cas ROOT=~/.dizzy-store/laptop BWLIMIT=2M scripts/seed_from_remote.sh
dizzy-store -d wd run --until-idle          # then the other devices catch up from this one
```

`scripts/seed_from_remote.sh` rsyncs a remote content-addressed tree (a server's `cas/`) into the device's
root — read-only on the remote (nothing is deleted there), niced, capped at `BWLIMIT`, interrupted files
resuming from `.store/tmp/rsync` — then adopts it in place, so every file is hashed against its name.
Re-running it copies only what is new. Time it first (`DRY_RUN=1` prints the byte count): a 4 Mbit/s
connection moves about 1.5–2 GiB an hour, so the first seed of a 30 GiB tree wants a fast connection or a night.

### Checking the copies yourself

The store's scrub and peer proofs are the working safety net. For a one-off "are these really the same
bytes?" two small tools trust nothing the store says:

```sh
scripts/cold_verify.py ROOT      # every blob hashed from the DISK (page cache dropped), compared with its name
(cd ROOT && find . -path ./.store -prune -o -type f -printf '%s %f %P\n') > laptop.txt   # a remote one: the same, over ssh
scripts/compare_manifests.py server server.txt laptop laptop.txt wd wd.txt
```

## What keeps data safe

- A copy **counts** toward `min_sites` only if it is present, on a non-draining
  device, and was proven good within the collection's `verify_max_age_days`
  (stored, or covered by a scrub pass measured from the pass's *start*).
- A device drops its own copy only after **asking** other devices to prove theirs:
  each peer re-hashes its file and reports its own live role and draining state.
  The log's claim is not proof, and neither is a matching file size.
- Reads that name a "hash" accept only a lowercase sha256, so nothing can be put,
  fetched or unlinked at a path a caller made up.
- The log is the truth; read models are a fold of it. A start that finds the
  "fold may be incomplete" marker (a crash mid-merge) rebuilds them from the log.
- A full disk is a recorded `blob_replication_failed(out_of_space)`, not a crash;
  an unreadable or missing blob is a scrub finding, not a stopped pass.

## Test

```sh
uv run --project store pytest store/tests             # everything (from the repo root)
uv run --project store pytest store/tests -k evict    # one behavior
```

- `scenarios/` — data-driven behavior specs over a simulated cluster (format:
  `scenarios/AUTHORING.md`; what each proves: `scenarios/*/about.md`).
- `tests/test_scenarios_http.py` — the SAME scenarios with every device serving
  the real peer API over real HTTP on localhost.
- `tests/test_daemon.py` — real daemons and the real CLI, end to end.
- `tests/test_idle.py` — `run --until-idle` against a real server on real sockets (a peer that cannot
  reach back, blobs nobody holds, a server that goes away); `test_idle_rules.py` — its timing rules against a
  scripted daemon, exactly. The tests never see the machine they run on: no real drives, no real user config.
- `tests/test_fetch.py`, `test_adopt_put.py`, `test_scrub.py`, `test_sweep.py`,
  `test_recovery.py`, `test_projections.py`, `test_storeutil.py` — what scenarios
  cannot see: what a failure records, which peer is asked first, resumable chunks,
  quarantine, back-off timing, crash recovery, fold-order insensitivity.
- `scripts/real_test.py` — two real devices as separate processes, `--mode local`
  (both here) or `--mode remote` (the second on a real server over an SSH tunnel, named by
  `SERVER_IP=…`; it uses a throwaway directory there and verifies it left nothing behind).

## Status

**Not standalone yet.** This is developed inside a checkout of the (private) dizzy-logger repository and
imports that repository's `host/` kit (engine, event store, replicator), `ext/dizzy` (DIZZY) and `dagstore`
by relative path — see `src/dizzy_store/_kit.py` and `[tool.uv.sources]` in `pyproject.toml`. It is
published to be read; running it needs that layout until DIZZY's runtime-kit extraction lets it stand alone.

The replication core is built and green in simulation, over HTTP and as real
processes; an independent review's findings (data-loss paths first) are fixed and
every safety rule is mutation-tested (`scripts/mutate.py`). The engine,
event store and replicator are imported from the logger's `host/` (see
`src/dizzy_store/_kit.py`) until DIZZY's runtime-kit extraction lands (seeds
dizzy-eea5, dizzy-ffdc). Installable as a tool, runs under a user systemd unit, guards its drives.
Not yet built: the logger's integration with the blob API, Tailscale as a first-class transport,
response compression.
