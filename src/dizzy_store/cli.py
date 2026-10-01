"""The `dizzy-store` command line.

    dizzy-store [-d DEVICE | --root DIR] [--config FILE] <command>

Which store a command acts on is found the way git finds a repository: what you said
(--root, -d NAME) beats the environment ($DIZZY_STORE_ROOT, $DIZZY_STORE_DEVICE) beats where you
are (the current directory, if it is a store) beats the configured default. A drive carries its own
state under <root>/.store/, so the intended use is: plug it in, `cd` into it, run the tool.

Set up (offline):            init · found · join · config
The daemon:                  run            (under systemd: `service install`, then `systemctl --user enable --now dizzy-store@NAME`)
Talk to the running daemon:  status · put · get · cmd · query · sweep · sync · tick
Look after the disk:         doctor · eject · drives
Look after the tool:         version · update · service

Exit status: 0 ok · 1 error · 2 usage · 74 the store's disk vanished while running ·
75 `run --until-idle` could not finish (no peer reachable, or what it wants is not to be had) ·
78 configuration (no such store, an unmounted drive, a port or a store already in use) —
systemd does not restart on 78.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from .config import CONFIG_TEMPLATE, SIZE_KEYS, ConfigError, DeviceSettings, load_config, resolve
from .device import Device
from .eject import run_eject
from .exitcodes import EX_CONFIG, EX_TEMPFAIL
from .lock import StoreLock
from storeutil import NotAStore, parse_size


def _kv(pairs: list[str]) -> dict[str, Any]:
    """key=value arguments; values are JSON when they parse (numbers, true, [..])."""
    out: dict[str, Any] = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        try:
            out[key] = json.loads(raw)
        except ValueError:
            out[key] = raw
    return out


def _device(args, root: Path) -> Device:
    """The store at ``root`` with this machine's settings for it laid over its state."""
    resolved = getattr(args, "resolved", None)
    return Device.load(root, resolved.settings if resolved else None)


def _client(args, root: Path):
    device = _device(args, root)
    host, port = device.host_port
    return (httpx.Client(base_url=f"http://{host}:{port}", timeout=None,
                         headers={"Authorization": f"Bearer {device['admin_token']}"}))


def _show(response: httpx.Response) -> int:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    print(json.dumps(body, indent=2, default=str) if not isinstance(body, str) else body)
    return 0 if response.is_success else 1


# ── commands ─────────────────────────────────────────────────────────────────

_SIZE_KEYS = SIZE_KEYS


_REMOVABLE_PREFIXES = ("/media/", "/run/media/", "/mnt/")


def _same_filesystem(a: str | Path, b: str | Path) -> bool:
    return os.stat(a).st_dev == os.stat(b).st_dev


def _check_init_location(root: Path, force: bool) -> None:
    """`init` is the one command allowed to make a store — so it must not make one by accident
    where a drive was supposed to be. Its parent must exist; and under a removable-media path the
    parent must be a DIFFERENT filesystem from `/`, or the drive is not actually mounted."""
    if force:
        return
    if not root.parent.is_dir():
        raise ConfigError(f"{root.parent} does not exist, so {root} cannot be made — is the drive mounted? "
                          "(init makes the store's own directory, never the path above it)")
    if str(root).startswith(_REMOVABLE_PREFIXES) and _same_filesystem(root.parent, "/"):
        raise ConfigError(f"{root.parent} is on the same filesystem as / — a drive that should be "
                          "mounted there is not (pass --force if you really mean to put the store here)")


def cmd_init(args, root: Path) -> int:
    resolved = args.resolved
    node_id = args.node_id or resolved.name
    if not node_id:
        raise ConfigError("name the device: --node-id NAME (or -d NAME to use its entry in the config)")
    limit = parse_size(args.limit_bytes) if args.limit_bytes else resolved.settings.limit
    if limit is None:
        raise ConfigError("no limit: pass --limit-bytes (e.g. 100GB) or set `limit:` for this device in the config")
    _check_init_location(root, args.force)
    config: dict[str, Any] = {"limit_bytes": limit}
    for key, value in _kv(args.config).items():       # --config high_watermark=0.9 ...
        config[key] = parse_size(value) if key in _SIZE_KEYS else value
    intervals = {k: v for k, v in _kv(args.interval).items()}
    device = Device.init(
        root, node_id=node_id, role=args.role, site=args.site,
        wants=[w for w in (args.wants or "").split(",") if w],
        location_note=args.location_note, listen=args.listen,
        endpoints=args.endpoint,
        seeds=dict(s.split("=", 1) for s in args.seed), peer_token=args.peer_token,
        config=config)
    if intervals:
        device.data["intervals"].update(intervals)
        device.save()
    print(f"initialized {node_id} at {root} (epoch {device['epoch']})")
    print(f"peer token (share with the other devices of this cluster): {device['peer_token']}")
    return 0


def cmd_found(args, root: Path) -> int:
    device = _device(args, root)
    if device["cluster_id"]:
        print(f"already in cluster {device['cluster_id']}", file=sys.stderr)
        return 1
    with StoreLock(root / ".store"):                    # not while a daemon is running this store
        return _found(args, device)


def _found(args, device: Device) -> int:
    node = device.build_node()
    cluster_id = args.cluster_id or f"c-{secrets.token_hex(4)}"
    node.run("create_cluster", cluster_id=cluster_id)
    node.adopt_cluster(cluster_id)
    device.data["cluster_id"] = cluster_id
    device.save()
    node.announce()
    node.close()
    print(f"founded cluster {cluster_id}")
    return 0


def cmd_join(args, root: Path) -> int:
    device = _device(args, root)
    token = args.peer_token or device["peer_token"]
    response = httpx.get(args.url.rstrip("/") + "/peer/cluster", timeout=10,
                         headers={"Authorization": f"Bearer {token}",
                                  "X-Peer-Id": device["node_id"]})
    response.raise_for_status()
    info = response.json()
    if not info.get("cluster_id"):
        print("that device has not founded a cluster yet", file=sys.stderr)
        return 1
    theirs, mine = info["cluster_id"], device["cluster_id"]
    if mine and mine != theirs:
        raise ConfigError(
            f"this store already belongs to cluster {mine!r}, and {info['node_id']} is in cluster {theirs!r} — "
            "joining would merge their event logs, and a merged log cannot be pulled apart again. A store belongs "
            f"to one cluster for life: to be part of {theirs!r}, make a new store with `init` and join that.")
    device.data["cluster_id"] = theirs
    device.data["peer_token"] = token
    device.remember_seed(info["node_id"], args.url.rstrip("/"))      # a route that is true on THIS computer
    device.save()
    print(f"joined cluster {info['cluster_id']} via {info['node_id']} at {args.url}")
    return 0


def cmd_run(args, root: Path) -> int:
    from .daemon import Daemon, IdlePolicy, serve
    # journald stamps every line itself; a second timestamp would only be noise
    fmt = ("%(levelname)s %(name)s %(message)s" if os.environ.get("JOURNAL_STREAM")
           else "%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.basicConfig(level=args.resolved.loaded.config.log_level.upper(), stream=sys.stdout, format=fmt)
    device = _device(args, root)
    if args.eject:                                       # find out BEFORE a long sync that there is nothing to eject
        why: list[str] = []
        if run_eject(root, None, dry_run=True, power_off=False, say=why.append) != 0:
            print("\n".join(m for m in why if m.startswith("error")), file=sys.stderr)
            print("--eject is for a store on a removable drive", file=sys.stderr)
            return EX_CONFIG
    reresolve = lambda: resolve(root=args.root, device=args.device, config_file=args.config_file)
    idle = IdlePolicy(max_s=args.wait) if args.until_idle else None
    code = 0
    with StoreLock(root / ".store"):                     # one daemon per store: refused BEFORE anything is opened
        logging.getLogger("dizzy_store").info(
            "starting %s (%s, site %s) on %s:%s", device["node_id"], device["role"],
            device["site"], *device.host_port)
        daemon = Daemon(device, reresolve=reresolve)
        try:
            code = serve(daemon, idle=idle, say=lambda text: print(text, flush=True))
        except KeyboardInterrupt:
            code = 0                                     # Ctrl-C is a normal way to stop it
        if daemon.idle_result is not None:
            print(daemon.idle_result[1], file=sys.stdout if code == 0 else sys.stderr, flush=True)
        if daemon.loop_done:
            with contextlib.suppress(Exception):         # best effort: a drive that has vanished cannot be closed cleanly,
                daemon.node.close()                      # and that must not change the exit status (74). An unmount needs it.
        elif args.eject and code == 0:
            print("the device is still busy writing — not unmounting it; run `dizzy-store eject` when it has stopped",
                  file=sys.stderr)
            code = EX_TEMPFAIL
    if args.eject and code == 0:
        os.chdir("/")                                    # and of this process's own working directory
        return run_eject(root, args.resolved.name)
    return code


def cmd_config(args, root: Optional[Path]) -> int:
    """Print the config template — or, with --show, what is in force and where it came from."""
    if not args.show:
        print(CONFIG_TEMPLATE, end="")
        return 0
    loaded = load_config(extra=args.config_file)
    print("# files looked at, in order of precedence (later wins):")
    for path in loaded.candidates:
        print(f"#   {'read   ' if path in loaded.files else 'absent '} {path}")
    print(yaml.safe_dump(loaded.config.model_dump(exclude_none=True), sort_keys=False).rstrip() or "{}")
    try:
        resolved = resolve(root=args.root, device=args.device, config_file=args.config_file, loaded=loaded)
        who = f"{resolved.name!r}" if resolved.name else "(not in the config)"
        print(f"\n# a command run here would act on: {who} at {resolved.root}")
    except ConfigError as exc:
        print(f"\n# {exc}")
    return 0


def cmd_version(args, root: Optional[Path]) -> int:
    from .tool import version_info
    for key, value in version_info().items():
        print(f"{key:14s} {value}")
    return 0


def cmd_doctor(args, root: Optional[Path]) -> int:
    """Probe a place for fitness as a store: facts, capabilities, optionally a benchmark."""
    from .doctor import probe, render
    settings, path = DeviceSettings(), args.path
    try:
        resolved = resolve(root=args.root, device=args.device, config_file=args.config_file)
        if path is None or Path(path).expanduser().resolve() == resolved.root.expanduser().resolve():
            settings, path = resolved.settings, str(resolved.root)
    except ConfigError:
        pass
    report = probe(Path(path or ".").expanduser(), bench_bytes=parse_size(args.bench) if args.bench else 0,
                   limit=settings.limit, min_free=settings.min_free, smart=not args.no_smart,
                   say=lambda text: print(text, file=sys.stderr, flush=True))
    print(json.dumps(report.to_dict(), indent=2) if args.json else render(report))
    return 1 if report.verdict == "fail" else 0


def cmd_eject(args, root: Path) -> int:
    return run_eject(root, args.resolved.name, dry_run=args.dry_run, power_off=not args.no_power_off)


def cmd_drives(args, root: Optional[Path]) -> int:
    """List the stores carried by the drives that are plugged in and mounted."""
    from .drives import find_stores
    found = find_stores()
    if args.json:
        print(json.dumps([{"name": f.node_id, "role": f.role, "site": f.site, "cluster": f.cluster_id,
                           "root": str(f.root), "device": f.source} for f in found], indent=2))
        return 0
    if not found:
        print("no mounted drive carries a store — plug it in and mount it "
              "(`udisksctl mount -b /dev/sdXN`; `lsblk -f` shows which), then try again")
        return 0
    configured = {}
    try:
        for name, dev in load_config(extra=args.config_file).config.devices.items():
            if dev.root:
                configured[str(Path(dev.root).expanduser())] = name
    except ConfigError:
        pass
    rows = [("NAME", "ROLE", "SITE", "CLUSTER", "AT")] + [
        (f.node_id, f.role, f.site, f.cluster_id or "(none yet)", str(f.root)) for f in found]
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    print(f"\nrun one anywhere with `dizzy-store -d {found[0].node_id} run` — no configuration needed")
    return 0


def cmd_update(args, root: Optional[Path]) -> int:
    from .tool import update
    return update(pull=args.pull, restart=not args.no_restart, dry_run=args.dry_run)


def cmd_service(args, root: Optional[Path]) -> int:
    from . import service
    if args.action == "uninstall":
        print("removed" if service.uninstall() else "was not installed")
        return 0
    exe = args.exe or service.default_exe()
    warning = service.exe_warning(exe)
    if warning:
        print(warning, file=sys.stderr)
    if args.action == "print":
        print(service.unit_text(exe), end="")
        return 0
    path = service.install(exe)
    print(f"installed {path}")
    print("run a device:   systemctl --user enable --now dizzy-store@NAME    (NAME is its entry in the config)")
    print("see it:         systemctl --user status dizzy-store@NAME     journalctl --user -u dizzy-store@NAME -f")
    print("change config:  edit config.yaml, then  systemctl --user reload dizzy-store@NAME")
    return 0


def cmd_status(args, root: Path) -> int:
    return _show(_client(args, root).get("/admin/status", params={"risk": args.risk}))


def cmd_put(args, root: Path) -> int:
    client, code = _client(args, root), 0
    for name in args.files:
        path = Path(name)
        with open(path, "rb") as f:
            response = client.put("/admin/blob", params={"collection": args.collection},
                                  content=iter(lambda: f.read(1 << 20), b""))
        if response.is_success:
            print(f"{response.json()['blob_hash']}  {path}")
        else:
            print(f"{path}: {response.text}", file=sys.stderr)
            code = 1
    return code


def cmd_get(args, root: Path) -> int:
    out = open(args.output, "wb") if args.output else sys.stdout.buffer
    digest = hashlib.sha256()
    with _client(args, root).stream("GET", f"/admin/blob/{args.blob_hash}") as response:
        if not response.is_success:
            response.read()
            print(response.text, file=sys.stderr)
            return 1
        for piece in response.iter_bytes(1 << 16):
            digest.update(piece)
            out.write(piece)
    if args.output:
        out.close()
    if digest.hexdigest() != args.blob_hash:
        print("received bytes do not match the hash!", file=sys.stderr)
        return 2
    return 0


def cmd_cmd(args, root: Path) -> int:
    return _show(_client(args, root).post("/admin/command", json={"name": args.name,
                                                             "fields": _kv(args.fields)}))


def cmd_query(args, root: Path) -> int:
    return _show(_client(args, root).post("/admin/query", json={"name": args.name,
                                                          "input": _kv(args.fields)}))


def cmd_sweep(args, root: Path) -> int:
    return _show(_client(args, root).post("/admin/sweep"))


def cmd_sync(args, root: Path) -> int:
    return _show(_client(args, root).post(f"/admin/sync/{args.peer}"))


def cmd_tick(args, root: Path) -> int:
    return _show(_client(args, root).post("/admin/tick"))


# ── entry point ──────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dizzy-store", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", help="act on the store at this directory")
    p.add_argument("-d", "--device", help="act on this device from the configuration "
                   "(default: $DIZZY_STORE_DEVICE, the store you are standing in, `default_device`)")
    p.add_argument("--config", dest="config_file", metavar="FILE",
                   help="one more configuration file, over the usual ones "
                        "(not to be confused with `init --config KEY=VALUE`)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create this device's identity under <root>/.store/")
    s.add_argument("--node-id", help="the device's name (default: the -d name)")
    s.add_argument("--role", required=True, choices=["hot", "archive", "cold"])
    s.add_argument("--site", required=True, help="where it physically lives (a failure domain)")
    s.add_argument("--wants", default="", help="comma-separated collections, or '*'")
    s.add_argument("--location-note")
    s.add_argument("--listen", help="where the daemon listens (default 127.0.0.1:7700; the config's `listen` wins)")
    s.add_argument("--endpoint", action="append", default=[],
                   help="URL peers reach this device at (repeatable)")
    s.add_argument("--seed", action="append", default=[], metavar="NAME=URL",
                   help="a peer to bootstrap from (repeatable)")
    s.add_argument("--peer-token", help="the cluster's shared peer token (generated if omitted)")
    s.add_argument("--limit-bytes", help="the most this device may hold, e.g. 20GB (or `limit:` in the config)")
    s.add_argument("--force", action="store_true",
                   help="make the store even where a drive looks unmounted (see the location check)")
    s.add_argument("--config", action="append", default=[], metavar="KEY=VALUE",
                   help="an env.store setting: high_watermark=0.9, chunk_size=8MB, live_window_s=600 …")
    s.add_argument("--interval", action="append", default=[], metavar="KEY=SECONDS",
                   help="a daemon cadence: sync_s=10, sweep_s=60, capacity_s=30, access_s=60, scrub_s=86400")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("found", help="found a new cluster from this device")
    s.add_argument("--cluster-id")
    s.set_defaults(fn=cmd_found)

    s = sub.add_parser("join", help="join the cluster a running peer belongs to")
    s.add_argument("--url", required=True)
    s.add_argument("--peer-token")
    s.set_defaults(fn=cmd_join)

    s = sub.add_parser("run", help="run the daemon (--until-idle: only until everything is synced)")
    s.add_argument("--until-idle", action="store_true",
                   help="plug in, sync, unplug: run until this device has exchanged logs with a peer, wants "
                        "nothing it lacks, and nothing has changed — then stop (exit 0), or exit 75 if it cannot finish")
    s.add_argument("--wait", type=float, metavar="SECONDS", help="with --until-idle: give up after this long")
    s.add_argument("--eject", action="store_true",
                   help="after a clean stop, unmount the drive and power it off (like `dizzy-store eject`)")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("status", help="what this device holds and knows")
    s.add_argument("--risk", action="store_true", help="also scan for blobs at risk (walks every blob)")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("put", help="store files (the edge's PUT)")
    s.add_argument("files", nargs="+")
    s.add_argument("--collection", default="default")
    s.set_defaults(fn=cmd_put)

    s = sub.add_parser("get", help="read a blob (fetched back from a peer if evicted here)")
    s.add_argument("blob_hash")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_get)

    s = sub.add_parser("cmd", help="dispatch any feat command: cmd set_collection_policy collection=photos ...")
    s.add_argument("name")
    s.add_argument("fields", nargs="*", metavar="KEY=VALUE")
    s.set_defaults(fn=cmd_cmd)

    s = sub.add_parser("query", help="run any feat query: query get_at_risk_blobs limit=10")
    s.add_argument("name")
    s.add_argument("fields", nargs="*", metavar="KEY=VALUE")
    s.set_defaults(fn=cmd_query)

    sub.add_parser("sweep", help="one paced catch-up tick").set_defaults(fn=cmd_sweep)
    s = sub.add_parser("sync", help="exchange logs with a peer now")
    s.add_argument("peer")
    s.set_defaults(fn=cmd_sync)
    sub.add_parser("tick", help="run every periodic job now").set_defaults(fn=cmd_tick)

    s = sub.add_parser("config", help="print the configuration template, or --show what is in force")
    s.add_argument("--show", action="store_true")
    s.set_defaults(fn=cmd_config, needs_root=False)
    sub.add_parser("version", help="what is running: version, source, commit, data fingerprint").set_defaults(
        fn=cmd_version, needs_root=False)
    s = sub.add_parser("doctor", help="is this place fit to hold a store? (filesystem, disk, capabilities, optional benchmark)")
    s.add_argument("path", nargs="?", help="the directory to probe (default: the chosen device's root, else here)")
    s.add_argument("--bench", nargs="?", const="1GB", metavar="SIZE",
                   help="also measure sustained writes, cold reads, hashing and small files (default 1GB; "
                        "20GB shows whether a drive's fast cache runs out)")
    s.add_argument("--no-smart", action="store_true", help="do not ask smartctl for the drive's health")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_doctor, needs_root=False)
    s = sub.add_parser("drives", help="list the stores on the drives that are plugged in and mounted")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_drives, needs_root=False)
    s = sub.add_parser("eject", help="stop the device, sync, unmount and power off its drive")
    s.add_argument("--dry-run", action="store_true", help="show the steps without running them")
    s.add_argument("--no-power-off", action="store_true")
    s.set_defaults(fn=cmd_eject)
    s = sub.add_parser("update", help="reinstall from the checkout and restart running devices")
    s.add_argument("--pull", action="store_true", help="git pull --ff-only first (refuses over uncommitted changes)")
    s.add_argument("--no-restart", action="store_true")
    s.add_argument("--dry-run", action="store_true", help="show the steps without running them")
    s.set_defaults(fn=cmd_update, needs_root=False)
    s = sub.add_parser("service", help="install the systemd user unit that runs devices")
    s.add_argument("action", choices=["install", "uninstall", "print"])
    s.add_argument("--exe", help="the dizzy-store executable the unit should run (default: the one on PATH)")
    s.set_defaults(fn=cmd_service, needs_root=False)
    p.set_defaults(needs_root=True)
    return p


def _names_a_store(args) -> bool:
    """Did the user (by flag or environment) say which store they mean?"""
    env = os.environ
    return bool(args.root or args.device or env.get("DIZZY_STORE_ROOT") or env.get("STORE_ROOT")
                or env.get("DIZZY_STORE_DEVICE"))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = None
        args.resolved = None
        if args.needs_root:
            root_flag = args.root
            if args.command == "init" and not _names_a_store(args):
                # `init` makes a store, so there is nothing to "find": with nothing said it means RIGHT HERE
                # (the drive-carries-its-own-state flow) — never `default_device`, which is for acting on one
                root_flag = str(Path.cwd())
            args.resolved = resolve(root=root_flag, device=args.device, config_file=args.config_file)
            root = args.resolved.root.expanduser().resolve()
        return args.fn(args, root)
    except (NotAStore, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EX_CONFIG                         # systemd: RestartPreventExitStatus=78 — don't spin
    except (FileNotFoundError, FileExistsError, httpx.HTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
