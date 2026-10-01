"""The layered machine configuration: precedence, validation, and how a command finds its store."""
import re
from pathlib import Path

import pytest
import yaml

from dizzy_store.config import (CONFIG_TEMPLATE, ConfigError, DeviceSettings, NoStoreChosen, StoreConfig,
                                candidate_files, load_config, resolve, store_from_here)

GiB = 1024 ** 3


def write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc) if not isinstance(doc, str) else doc)
    return path


# ── layering ─────────────────────────────────────────────────────────────────

def test_layers_merge_in_precedence_order(tmp_path):
    system = write(tmp_path / "etc.yaml", {"log_level": "warning", "devices": {
        "laptop": {"root": "/srv/a", "limit": "50GB", "listen": "127.0.0.1:7701"}}})
    user = write(tmp_path / "user.yaml", {"devices": {"laptop": {"limit": "100GB"}, "wd": {"root": "/m/wd"}}})
    project = write(tmp_path / "proj.yaml", {"log_level": "debug",
                                             "devices": {"laptop": {"endpoints": ["http://x"]}}})
    loaded = load_config(files=[system, user, project], env={})
    laptop = loaded.config.devices["laptop"]
    assert loaded.config.log_level == "debug"                       # the later file wins…
    assert laptop.limit == 100 * GiB                                # …per key,
    assert laptop.listen == "127.0.0.1:7701" and laptop.root == "/srv/a"   # and earlier keys survive
    assert laptop.endpoints == ["http://x"]
    assert loaded.config.devices["wd"].root == "/m/wd"
    assert loaded.files == [system, user, project]


def test_lists_are_replaced_and_mappings_merge(tmp_path):
    a = write(tmp_path / "a.yaml", {"devices": {"d": {"root": "/r", "endpoints": ["http://one", "http://two"],
                                                      "seeds": {"x": "http://x"}, "intervals": {"sync_s": 5}}}})
    b = write(tmp_path / "b.yaml", {"devices": {"d": {"endpoints": ["http://three"],
                                                      "seeds": {"y": "http://y"}, "intervals": {"sweep_s": 9}}}})
    d = load_config(files=[a, b], env={}).config.devices["d"]
    assert d.endpoints == ["http://three"]
    assert d.seeds == {"x": "http://x", "y": "http://y"}
    assert d.intervals == {"sync_s": 5, "sweep_s": 9}


def test_files_that_are_not_there_are_skipped(tmp_path):
    real = write(tmp_path / "real.yaml", {"log_level": "error"})
    loaded = load_config(files=[tmp_path / "nope.yaml", real, tmp_path / "also-nope.yaml"], env={})
    assert loaded.files == [real] and len(loaded.candidates) == 3
    assert load_config(files=[tmp_path / "nope.yaml"], env={}).config == StoreConfig()


def test_the_search_path_is_the_documented_one(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg"), "DIZZY_STORE_CONFIG": "~/extra.yaml"}
    files = candidate_files(env, tmp_path / "cwd", extra="/flag.yaml")
    assert files == [Path("/etc/dizzy-store/config.yaml"), tmp_path / "xdg" / "dizzy-store" / "config.yaml",
                     tmp_path / "cwd" / ".dizzy-store.yaml", Path("~/extra.yaml").expanduser(), Path("/flag.yaml")]
    home = candidate_files({}, tmp_path)
    assert home[1] == Path.home() / ".config" / "dizzy-store" / "config.yaml"


def test_a_relative_root_is_relative_to_the_file_that_says_so(tmp_path):
    drive = tmp_path / "drive" / "dizzy-store"
    here = write(drive / ".dizzy-store.yaml", {"devices": {"wd": {"root": "."}, "sub": {"root": "data/blobs"}}})
    cfg = load_config(files=[here], env={}).config
    assert Path(cfg.devices["wd"].root) == drive
    assert Path(cfg.devices["sub"].root) == drive / "data" / "blobs"


def test_sizes_are_binary_and_may_be_numbers(tmp_path):
    f = write(tmp_path / "c.yaml", {"devices": {"d": {"root": "/r", "limit": "100GB", "min_free": 2048,
                                                      "pacing": {"max_bytes_per_sec": "5MB"},
                                                      "settings": {"chunk_size": "8MB", "high_watermark": 0.8}}}})
    d = load_config(files=[f], env={}).config.devices["d"]
    assert d.env_store() == {"limit_bytes": 100 * GiB, "min_free_bytes": 2048, "max_bytes_per_sec": 5 * 1024 ** 2,
                             "chunk_size": 8 * 1024 ** 2, "high_watermark": 0.8}


def test_named_settings_beat_the_raw_settings_block():
    d = DeviceSettings(limit="1GB", settings={"limit_bytes": 5})
    assert d.env_store()["limit_bytes"] == GiB


# ── validation ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("doc, needle", [
    ({"devices": {"d": {"root": "/r", "limt": "1GB"}}}, "limt"),                 # a typo is an error, not silence
    ({"devicez": {}}, "devicez"),
    ({"devices": {"d": {"root": "/r", "limit": "lots"}}}, "limit"),
    ({"log_level": "chatty"}, "log_level"),
    ({"defaults": {"root": "/r"}}, "root"),
    ({"devices": {"d": {"pacing": {"max_bytes_per_sec": "fast"}}}}, "pacing"),
])
def test_bad_configuration_is_refused_with_the_reason(tmp_path, doc, needle):
    f = write(tmp_path / "c.yaml", doc)
    with pytest.raises(ConfigError) as excinfo:
        load_config(files=[f], env={})
    assert needle in str(excinfo.value)


def test_unreadable_files_are_named(tmp_path):
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(files=[write(tmp_path / "bad.yaml", "devices: [unclosed")], env={})
    with pytest.raises(ConfigError, match="mapping"):
        load_config(files=[write(tmp_path / "list.yaml", "- a\n- b\n")], env={})


def test_the_environment_overrides_the_log_level(tmp_path):
    f = write(tmp_path / "c.yaml", {"log_level": "warning"})
    assert load_config(files=[f], env={"DIZZY_STORE_LOG_LEVEL": "debug"}).config.log_level == "debug"
    with pytest.raises(ConfigError):
        load_config(files=[f], env={"DIZZY_STORE_LOG_LEVEL": "loud"})


def test_the_template_is_valid_against_the_schema():
    """Every key the shipped template advertises must be one the loader accepts — uncomment its
    examples and load them."""
    lines = []
    for line in CONFIG_TEMPLATE.splitlines():
        m = re.match(r"^#( ?)(\s*[A-Za-z_]+:.*)$", line)
        if m and not line.startswith("#   /") and "Place this file" not in line:
            lines.append(m.group(2))
    doc = yaml.safe_load("\n".join(lines))
    assert set(doc["devices"]) == {"laptop"}                       # a portable drive needs no entry at all
    cfg = StoreConfig.model_validate(doc)
    assert cfg.devices["laptop"].limit == 100 * GiB and cfg.devices["laptop"].min_free == 20 * GiB
    assert cfg.defaults.site == "home" and cfg.defaults.intervals["sync_s"] == 30


# ── which store a command acts on ────────────────────────────────────────────

@pytest.fixture
def cfg_file(tmp_path):
    return write(tmp_path / "cfg" / "config.yaml", {
        "default_device": "laptop",
        "defaults": {"intervals": {"sync_s": 7}, "pacing": {"max_bytes_per_sec": "1MB"}},
        "devices": {"laptop": {"root": str(tmp_path / "laptop"), "listen": "127.0.0.1:7701",
                               "intervals": {"sweep_s": 9}},
                    "wd": {"root": str(tmp_path / "wd"), "listen": "127.0.0.1:7703"}}})


def pick(cfg_file, tmp_path, **kw):
    kw.setdefault("env", {})
    kw.setdefault("cwd", tmp_path / "elsewhere")
    return resolve(config_file=str(cfg_file), loaded=load_config(files=[cfg_file], env={}), **kw)


def test_what_you_said_beats_the_environment_beats_where_you_are_beats_the_default(cfg_file, tmp_path):
    here = tmp_path / "here"
    (here / ".store").mkdir(parents=True)
    (here / ".store" / "device.json").write_text("{}")
    assert pick(cfg_file, tmp_path).name == "laptop"                                          # the default
    assert pick(cfg_file, tmp_path, cwd=here).root == here                                    # a store under your feet…
    assert pick(cfg_file, tmp_path, cwd=here, env={"DIZZY_STORE_DEVICE": "wd"}).name == "wd"  # …loses to the environment
    assert pick(cfg_file, tmp_path, env={"DIZZY_STORE_DEVICE": "wd"}).name == "wd"
    assert pick(cfg_file, tmp_path, env={"DIZZY_STORE_ROOT": "/x"}, device="wd").name == "wd"   # …which loses to a flag
    assert pick(cfg_file, tmp_path, root="/y", device="wd").root == Path("/y")                # --root is the most specific
    assert pick(cfg_file, tmp_path, env={"STORE_ROOT": "/legacy"}).root == Path("/legacy")    # the old variable still works


def test_a_root_that_a_configured_device_lives_at_gets_that_devices_settings(cfg_file, tmp_path):
    r = pick(cfg_file, tmp_path, root=str(tmp_path / "wd"))
    assert r.name == "wd" and r.settings.listen == "127.0.0.1:7703"
    stranger = pick(cfg_file, tmp_path, root=str(tmp_path / "unknown"))
    assert stranger.name is None and stranger.settings.listen is None       # only the defaults apply


def test_device_settings_sit_over_the_defaults(cfg_file, tmp_path):
    s = pick(cfg_file, tmp_path, device="laptop").settings
    assert s.intervals == {"sync_s": 7, "sweep_s": 9}                       # merged, not replaced
    assert s.env_store() == {"max_bytes_per_sec": 1024 ** 2}


def test_the_only_configured_device_needs_no_name(tmp_path):
    f = write(tmp_path / "c.yaml", {"devices": {"solo": {"root": str(tmp_path / "solo")}}})
    r = resolve(env={}, cwd=tmp_path, loaded=load_config(files=[f], env={}))
    assert r.name == "solo"


def test_no_choice_is_an_error_that_says_what_is_known(tmp_path):
    f = write(tmp_path / "c.yaml", {"devices": {"a": {"root": "/a"}, "b": {"root": "/b"}}})
    with pytest.raises(NoStoreChosen, match="a, b"):
        resolve(env={}, cwd=tmp_path, loaded=load_config(files=[f], env={}))
    with pytest.raises(NoStoreChosen, match="no devices are configured"):
        resolve(env={}, cwd=tmp_path, loaded=load_config(files=[], env={}))


def test_unknown_or_rootless_devices_are_errors(cfg_file, tmp_path):
    with pytest.raises(ConfigError, match="no device named 'nope'.*known: laptop, wd"):
        pick(cfg_file, tmp_path, device="nope")
    f = write(tmp_path / "c.yaml", {"devices": {"floating": {"listen": "127.0.0.1:1"}}})
    with pytest.raises(ConfigError, match="no `root:`"):
        resolve(device="floating", env={}, cwd=tmp_path, loaded=load_config(files=[f], env={}))


# ── finding the store you are standing in or beside ──────────────────────────

def make_store(path: Path) -> Path:
    (path / ".store").mkdir(parents=True)
    (path / ".store" / "device.json").write_text("{}")
    return path


def test_a_store_is_found_from_inside_it_like_git_finds_a_repository(tmp_path):
    store = make_store(tmp_path / "drive" / "dizzy-store")
    deep = store / "ab" / "cd"
    deep.mkdir(parents=True)
    assert store_from_here(store) == store
    assert store_from_here(deep) == store                       # any depth below it
    assert store_from_here(tmp_path / "elsewhere") is None


def test_the_conventional_folder_on_a_drive_is_found_from_the_drives_top(tmp_path):
    drive = tmp_path / "media" / "WD"
    store = make_store(drive / "dizzy-store")
    assert store_from_here(drive) == store                      # `cd /media/you/WD` is enough
    other = tmp_path / "media" / "USB"
    (other / "photos").mkdir(parents=True)
    assert store_from_here(other) is None
    assert store_from_here(other / "photos") is None


def test_resolve_uses_what_you_stand_in_before_the_default(tmp_path):
    cfg = write(tmp_path / "cfg.yaml", {"default_device": "laptop",
                                        "devices": {"laptop": {"root": str(tmp_path / "laptop")}}})
    store = make_store(tmp_path / "drive" / "dizzy-store")
    r = resolve(env={}, cwd=store / "ab", loaded=load_config(files=[cfg], env={}))
    assert r.root == store and r.name is None
    r = resolve(env={}, cwd=tmp_path / "drive", loaded=load_config(files=[cfg], env={}))
    assert r.root == store
    r = resolve(env={}, cwd=tmp_path / "nowhere", loaded=load_config(files=[cfg], env={}))
    assert r.name == "laptop"


def test_a_machine_wide_site_applies_to_every_device_run_there(cfg_file, tmp_path):
    f = write(tmp_path / "site.yaml", {"defaults": {"site": "office"},
                                       "devices": {"laptop": {"root": str(tmp_path / "l")},
                                                   "fixed": {"root": str(tmp_path / "f"), "site": "datacentre"}}})
    loaded = load_config(files=[f], env={})
    assert resolve(device="laptop", env={}, cwd=tmp_path, loaded=loaded).settings.site == "office"
    assert resolve(device="fixed", env={}, cwd=tmp_path, loaded=loaded).settings.site == "datacentre"
    assert resolve(root=str(tmp_path / "somewhere"), env={}, cwd=tmp_path, loaded=loaded).settings.site == "office"
