"""Machine configuration: where THIS machine's stores live and how it runs them.

Layered like DIZZY's own config (dizzy/config.py) — YAML files merged system → user →
project, then environment variables, then command-line flags:

    /etc/dizzy-store/config.yaml
    $XDG_CONFIG_HOME/dizzy-store/config.yaml      (~/.config/dizzy-store/config.yaml)
    ./.dizzy-store.yaml                           (the current directory: `cd` into a drive and run)
    $DIZZY_STORE_CONFIG                           (one more file, if set)
    --config FILE                                 (one more, if given)

Later files win; mappings merge key by key, lists are replaced. A relative ``root:`` is relative
to the file that says it, so a config sitting next to a drive's data can simply say ``root: .``.

The split that matters: what a device IS (identity, role, site, wants) travels with its data, in
<root>/.store/device.json; THIS file says how a machine finds and runs it — root, listen address,
whom to dial, cadence, limits, pacing, log level. Move a drive to another computer and only this
changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Mapping, Optional

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError

from storeutil import parse_size

# env.store fields that are byte counts: accept "100GB" as well as 107374182400
SIZE_KEYS = {"limit_bytes", "min_free_bytes", "chunk_threshold_bytes", "chunk_size",
             "max_bytes_per_sec", "scrub_bytes_per_sec", "scrub_budget_bytes"}

Size = Annotated[int, BeforeValidator(parse_size)]

CONFIG_TEMPLATE = """\
# dizzy-store configuration
# Place this file at one of (later ones win; mappings merge, lists are replaced):
#   /etc/dizzy-store/config.yaml            — system-level
#   ~/.config/dizzy-store/config.yaml       — user-level
#   ./.dizzy-store.yaml                     — project-level: the current directory
#   $DIZZY_STORE_CONFIG, --config FILE      — one more file each
# Environment variables (DIZZY_STORE_DEVICE, DIZZY_STORE_ROOT, DIZZY_STORE_LOG_LEVEL) override files;
# command-line flags override everything. `dizzy-store config --show` prints what ended up in force.
#
# What a device IS (its name, role, site, wants) lives with its data, set by `dizzy-store init`.
# This file is how THIS machine finds and runs devices. Sizes are binary: 100GB = 100 GiB.

# Which device a bare `dizzy-store status` talks to (optional when there is only one).
# default_device: laptop

# debug | info | warning | error
# log_level: info

# Settings applied under every device below.
# defaults:
#   site: home                                   # where THIS machine is: every device run here announces it —
#                                                # a portable drive's failure domain is wherever it is plugged in
#   intervals: {sync_s: 30, sweep_s: 60, capacity_s: 60, access_s: 60, scrub_s: 86400}
#   pacing: {max_bytes_per_sec: 0, scrub_bytes_per_sec: 0}      # 0 = unlimited

# devices:
#   laptop:
#     root: ~/.dizzy-store/laptop          # the blob tree and <root>/.store/; a relative path is
#                                          # relative to THIS file
#     listen: 127.0.0.1:7701               # where this machine's daemon listens
#     endpoints: [http://127.0.0.1:7701]   # what peers should dial (announced to the cluster)
#     seeds: {server: http://127.0.0.1:7702}   # peers to bootstrap from
#     limit: 100GB                         # the most this device may hold in blobs
#     min_free: 20GB                       # the filesystem must always keep this much free
#     settings: {high_watermark: 0.9}      # any other env.store field (advanced)
# A PORTABLE drive needs no entry here: its name, role, limits and identity live on the drive, and
# `dizzy-store -d NAME` (or standing in/beside its dizzy-store folder) finds it wherever it is mounted.
"""


class ConfigError(Exception):
    """The configuration is unusable — a bad file, no device to act on. Exit status 78."""


class NoStoreChosen(ConfigError):
    """Nothing says which store to act on (and `init` may then mean "right here")."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")      # a typo in a hand-written file is an error, not silence


class Pacing(_Strict):
    max_bytes_per_sec: Optional[Size] = None
    scrub_bytes_per_sec: Optional[Size] = None


class DeviceSettings(_Strict):
    root: Optional[str] = None
    site: Optional[str] = None              # where THIS machine is: overrides the drive's own site while it is here
    location_note: Optional[str] = None
    listen: Optional[str] = None
    endpoints: Optional[list[str]] = None
    seeds: Optional[dict[str, str]] = None
    limit: Optional[Size] = None
    min_free: Optional[Size] = None
    intervals: Optional[dict[str, Any]] = None
    pacing: Optional[Pacing] = None
    settings: Optional[dict[str, Any]] = None

    def env_store(self) -> dict[str, Any]:
        """The env.store overrides these settings stand for (named keys beat raw ``settings``)."""
        out = {k: (parse_size(v) if k in SIZE_KEYS else v) for k, v in (self.settings or {}).items()}
        if self.limit is not None:
            out["limit_bytes"] = self.limit
        if self.min_free is not None:
            out["min_free_bytes"] = self.min_free
        if self.pacing:
            for key in ("max_bytes_per_sec", "scrub_bytes_per_sec"):
                if getattr(self.pacing, key) is not None:
                    out[key] = getattr(self.pacing, key)
        return out

    def merged_under(self, base: "DeviceSettings") -> "DeviceSettings":
        """These settings over ``base``: mappings merge key by key, anything else replaces."""
        return DeviceSettings.model_validate(
            _deep_merge(base.model_dump(exclude_none=True), self.model_dump(exclude_none=True)))


class StoreConfig(_Strict):
    default_device: Optional[str] = None
    log_level: str = "info"
    defaults: DeviceSettings = DeviceSettings()
    devices: dict[str, DeviceSettings] = {}


@dataclass
class Loaded:
    config: StoreConfig
    files: list[Path] = field(default_factory=list)          # the files that existed and were read
    candidates: list[Path] = field(default_factory=list)     # every place that was looked at, in order


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def user_config_dir(env: Mapping[str, str]) -> Path:
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "dizzy-store"


def candidate_files(env: Mapping[str, str], cwd: Path, extra: Optional[str] = None) -> list[Path]:
    files = [Path("/etc/dizzy-store/config.yaml"), user_config_dir(env) / "config.yaml",
             Path(cwd) / ".dizzy-store.yaml"]
    for path in (env.get("DIZZY_STORE_CONFIG"), extra):
        if path:
            files.append(Path(path).expanduser())
    return files


def _read(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: a config file is a mapping, got {type(raw).__name__}")
    # a relative root means "relative to the file that says so"
    for name, device in (raw.get("devices") or {}).items():
        if isinstance(device, dict) and device.get("root"):
            root = Path(str(device["root"])).expanduser()
            device["root"] = str(root if root.is_absolute() else (path.parent / root).resolve())
    return raw


def load_config(env: Optional[Mapping[str, str]] = None, cwd: Optional[Path] = None,
                extra: Optional[str] = None, files: Optional[list[Path]] = None) -> Loaded:
    """Merge the layers, apply environment overrides, validate. ``files`` replaces the search path
    (tests, and callers that know exactly which files they mean)."""
    env = os.environ if env is None else env
    cwd = Path.cwd() if cwd is None else Path(cwd)
    candidates = files if files is not None else candidate_files(env, cwd, extra)
    merged: dict[str, Any] = {}
    read: list[Path] = []
    for path in candidates:
        if path.is_file():
            merged = _deep_merge(merged, _read(path))
            read.append(path)
    if level := env.get("DIZZY_STORE_LOG_LEVEL"):
        merged["log_level"] = level
    try:
        config = StoreConfig.model_validate(merged)
    except ValidationError as exc:
        where = ", ".join(str(p) for p in read) or "the environment"
        problems = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"bad configuration (from {where}): {problems}") from exc
    if config.defaults.root:
        raise ConfigError("`defaults` cannot set a root: a root belongs to one device")
    if config.log_level.lower() not in ("debug", "info", "warning", "error"):
        raise ConfigError(f"log_level must be debug, info, warning or error, not {config.log_level!r}")
    return Loaded(config, read, list(candidates))


from .drives import STORE_DIRNAME  # noqa: E402  (where a store lives on a drive: <mount>/dizzy-store)


def _discover() -> list:
    """The stores on mounted drives (a function of its own so tests can keep the real machine out of them)."""
    from .drives import find_stores
    return find_stores()


def store_from_here(cwd: Path) -> Optional[Path]:
    """The store the current directory is in or beside — the way git finds a repository: this
    directory or any parent that IS a store, else this directory's `dizzy-store/` child (the
    conventional folder on a drive, so `cd /media/you/WD` is enough)."""
    for directory in (cwd, *cwd.parents):
        if (directory / ".store" / "device.json").is_file():
            return directory
    child = cwd / STORE_DIRNAME
    return child if (child / ".store" / "device.json").is_file() else None


@dataclass
class Resolved:
    """Which store a command acts on, and this machine's settings for it."""
    root: Path
    name: Optional[str]
    settings: DeviceSettings
    loaded: Loaded


def _same_dir(a: str | Path, b: str | Path) -> bool:
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except OSError:
        return False


def resolve(*, root: Optional[str] = None, device: Optional[str] = None,
            env: Optional[Mapping[str, str]] = None, cwd: Optional[Path] = None,
            config_file: Optional[str] = None, loaded: Optional[Loaded] = None) -> Resolved:
    """Pick the store a command acts on. Like git finds a repository: what you said beats what the
    environment says beats where you are beats the default —

        --root, --device, $DIZZY_STORE_ROOT / $STORE_ROOT, $DIZZY_STORE_DEVICE,
        the store you are in or beside (``store_from_here``), ``default_device``, the only configured device.
    """
    env = os.environ if env is None else env
    cwd = Path.cwd() if cwd is None else Path(cwd)
    loaded = loaded or load_config(env, cwd, config_file)
    cfg = loaded.config

    def by_name(name: str) -> Resolved:
        if name not in cfg.devices:
            # not configured here: a portable drive carries its own name — is one mounted?
            drives = _discover()
            carrying = [f for f in drives if f.node_id == name]
            if len(carrying) == 1:
                return Resolved(carrying[0].root, name, cfg.defaults, loaded)
            if carrying:
                where = "; ".join(str(f.root) for f in carrying)
                raise ConfigError(f"{len(carrying)} mounted drives carry a store named {name!r} ({where}) — "
                                  "say which with --root PATH")
            known = ", ".join(sorted(set(cfg.devices) | {f.node_id for f in drives})) or "none"
            raise ConfigError(f"no device named {name!r} in the configuration or on a mounted drive "
                              f"(known: {known}); see `dizzy-store config --show` and `dizzy-store drives`")
        settings = cfg.devices[name].merged_under(cfg.defaults)
        if not settings.root:
            raise ConfigError(f"device {name!r} has no `root:` in the configuration")
        return Resolved(Path(settings.root).expanduser(), name, settings, loaded)

    def by_root(path: str | Path) -> Resolved:
        path = Path(path).expanduser()
        for name, dev in cfg.devices.items():            # a configured device that lives here?
            if dev.root and _same_dir(dev.root, path):
                return Resolved(path, name, dev.merged_under(cfg.defaults), loaded)
        return Resolved(path, None, cfg.defaults, loaded)

    if root:
        return by_root(root)
    if device:
        return by_name(device)
    if env_root := env.get("DIZZY_STORE_ROOT") or env.get("STORE_ROOT"):
        return by_root(env_root)
    if env_device := env.get("DIZZY_STORE_DEVICE"):
        return by_name(env_device)
    if here := store_from_here(cwd):
        return by_root(here)
    if cfg.default_device:
        return by_name(cfg.default_device)
    if len(cfg.devices) == 1:
        return by_name(next(iter(cfg.devices)))
    known = ", ".join(sorted(cfg.devices))
    raise NoStoreChosen("no store chosen: run from inside one, or pass -d NAME / --root PATH, or set "
                      f"`default_device` ({'known devices: ' + known if known else 'no devices are configured'}; "
                      "`dizzy-store config` prints a template)")
