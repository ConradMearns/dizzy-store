"""Finding the stores on plugged-in drives: what a portable drive needs instead of a config entry."""
import json
from pathlib import Path

import pytest
import yaml

from conftest import mountinfo_line
from dizzy_store import config, drives
from dizzy_store.cli import main as cli
from dizzy_store.config import ConfigError, load_config, resolve
from dizzy_store.drives import FoundStore, find_stores
from dizzy_store.volumes import parse_mountinfo


def store_at(path: Path, node_id="wd", role="cold", site="home", cluster="c-1") -> Path:
    (path / ".store").mkdir(parents=True)
    (path / ".store" / "device.json").write_text(json.dumps(
        {"node_id": node_id, "role": role, "site": site, "cluster_id": cluster}))
    return path


def mounts_for(*mountpoints, fstype="ext4", source="/dev/sdb1"):
    return parse_mountinfo("\n".join(mountinfo_line(40 + i, f"8:{i}", str(mp), fstype, source)
                                     for i, mp in enumerate(mountpoints)))


def test_a_store_in_the_conventional_folder_is_found(tmp_path):
    root = store_at(tmp_path / "media" / "WD" / "dizzy-store")
    (found,) = find_stores(mounts_for(tmp_path / "media" / "WD"))
    assert found == FoundStore(root, "wd", "cold", "home", "c-1", str(tmp_path / "media" / "WD"), "/dev/sdb1")


def test_a_drive_dedicated_to_the_store_is_found_at_its_top(tmp_path):
    root = store_at(tmp_path / "media" / "BACKUP")
    assert [f.root for f in find_stores(mounts_for(tmp_path / "media" / "BACKUP"))] == [root]


def test_the_system_volume_network_mounts_and_empty_drives_are_not_looked_at(tmp_path):
    store_at(tmp_path / "dizzy-store")
    (tmp_path / "media" / "EMPTY").mkdir(parents=True)
    mounts = parse_mountinfo("\n".join([
        mountinfo_line(1, "259:1", "/", "ext4", "/dev/mapper/root"),
        mountinfo_line(2, "0:50", str(tmp_path), "nfs4", "server:/export"),
        mountinfo_line(3, "8:2", str(tmp_path / "media" / "EMPTY"), "ext4", "/dev/sdc1")]))
    assert find_stores(mounts) == []


def test_a_garbled_device_file_is_skipped_not_fatal(tmp_path):
    bad = tmp_path / "media" / "BAD" / "dizzy-store"
    (bad / ".store").mkdir(parents=True)
    (bad / ".store" / "device.json").write_text("{not json")
    good = store_at(tmp_path / "media" / "GOOD" / "dizzy-store", node_id="ok")
    assert [f.root for f in find_stores(mounts_for(tmp_path / "media" / "BAD", tmp_path / "media" / "GOOD"))] == [good]


def test_two_mounts_of_one_folder_are_one_store_and_the_list_is_sorted(tmp_path):
    store_at(tmp_path / "m1" / "dizzy-store", node_id="zeta")
    store_at(tmp_path / "m2" / "dizzy-store", node_id="alpha")
    found = find_stores(mounts_for(tmp_path / "m1", tmp_path / "m2", tmp_path / "m1"))
    assert [f.node_id for f in found] == ["alpha", "zeta"]


# ── `-d NAME` finds a mounted drive's store without any configuration ────────

@pytest.fixture
def on_a_drive(tmp_path, monkeypatch):
    root = store_at(tmp_path / "media" / "WD" / "dizzy-store")
    found = [FoundStore(root, "wd", "cold", "home", "c-1", str(tmp_path / "media" / "WD"), "/dev/sdb1")]
    monkeypatch.setattr(config, "_discover", lambda: found)
    return root


def configured(tmp_path, **devices):
    f = tmp_path / "cfg.yaml"
    f.write_text(yaml.safe_dump({"defaults": {"site": "office"}, "devices": devices}))
    return load_config(files=[f], env={})


def test_a_device_name_that_is_not_configured_is_looked_for_on_the_mounted_drives(tmp_path, on_a_drive):
    r = resolve(device="wd", env={}, cwd=tmp_path, loaded=configured(tmp_path))
    assert r.root == on_a_drive and r.name == "wd"
    assert r.settings.site == "office"                    # this machine's defaults still apply to it


def test_a_configured_device_beats_a_drive_of_the_same_name(tmp_path, on_a_drive):
    other = tmp_path / "configured-wd"
    r = resolve(device="wd", env={}, cwd=tmp_path, loaded=configured(tmp_path, wd={"root": str(other)}))
    assert r.root == other


def test_two_drives_with_one_name_are_ambiguous_not_guessed(tmp_path, monkeypatch):
    a = FoundStore(tmp_path / "a", "wd", "cold", "home", "c", "/m/a", "/dev/sdb1")
    b = FoundStore(tmp_path / "b", "wd", "cold", "home", "c", "/m/b", "/dev/sdc1")
    monkeypatch.setattr(config, "_discover", lambda: [a, b])
    with pytest.raises(ConfigError, match="2 mounted drives carry a store named 'wd'.*--root"):
        resolve(device="wd", env={}, cwd=tmp_path, loaded=configured(tmp_path))


def test_an_unknown_name_lists_both_what_is_configured_and_what_is_plugged_in(tmp_path, on_a_drive):
    with pytest.raises(ConfigError, match=r"no device named 'nope'.*known: laptop, wd"):
        resolve(device="nope", env={}, cwd=tmp_path,
                loaded=configured(tmp_path, laptop={"root": str(tmp_path / "l")}))


# ── the command ──────────────────────────────────────────────────────────────

def test_drives_lists_what_is_plugged_in(tmp_path, capsys, monkeypatch):
    root = store_at(tmp_path / "media" / "WD" / "dizzy-store", node_id="wd", site="home")
    monkeypatch.setattr(drives.volumes, "read_mounts", lambda *a: mounts_for(tmp_path / "media" / "WD"))
    assert cli(["drives"]) == 0
    out = capsys.readouterr().out
    assert "NAME" in out and "wd" in out and "cold" in out and str(root) in out
    assert "dizzy-store -d wd run" in out
    assert cli(["drives", "--json"]) == 0
    (row,) = json.loads(capsys.readouterr().out)
    assert row["name"] == "wd" and row["root"] == str(root)


def test_drives_says_what_to_do_when_nothing_is_there(capsys, monkeypatch):
    monkeypatch.setattr(drives.volumes, "read_mounts", lambda *a: [])
    assert cli(["drives"]) == 0
    assert "mount it" in capsys.readouterr().out


# ── `init` means "right here" ────────────────────────────────────────────────

@pytest.fixture
def configured_laptop(tmp_path, monkeypatch):
    """A machine with a default device — the situation in which `init` once made a drive's store at the laptop."""
    laptop = tmp_path / "laptop-store"
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(yaml.safe_dump({"default_device": "laptop", "devices": {"laptop": {"root": str(laptop)}}}))
    monkeypatch.setenv("DIZZY_STORE_CONFIG", str(cfg))
    return laptop


def test_init_makes_the_store_right_here_not_at_the_default_device(configured_laptop, tmp_path, monkeypatch):
    drive = tmp_path / "WD" / "dizzy-store"
    drive.mkdir(parents=True)
    monkeypatch.chdir(drive)
    assert cli(["init", "--node-id", "wd", "--role", "cold", "--site", "home", "--limit-bytes", "1GB"]) == 0
    assert (drive / ".store" / "device.json").is_file()
    assert not configured_laptop.exists()                  # the laptop's store was not touched, or created


def test_init_that_names_a_store_still_means_that_store(configured_laptop, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert cli(["-d", "laptop", "init", "--node-id", "laptop", "--role", "archive", "--site", "home", "--limit-bytes", "1GB"]) == 0
    assert (configured_laptop / ".store" / "device.json").is_file() and not (elsewhere / ".store").exists()
    other = tmp_path / "other"
    assert cli(["--root", str(other), "init", "--node-id", "o", "--role", "cold", "--site", "home", "--limit-bytes", "1GB"]) == 0
    assert (other / ".store" / "device.json").is_file() and not (elsewhere / ".store").exists()
    monkeypatch.setenv("DIZZY_STORE_ROOT", str(tmp_path / "from-env"))
    assert cli(["init", "--node-id", "e", "--role", "cold", "--site", "home", "--limit-bytes", "1GB"]) == 0     # the environment names one too
    assert (tmp_path / "from-env" / ".store" / "device.json").is_file() and not (elsewhere / ".store").exists()


def test_a_command_run_inside_a_drives_folder_acts_on_that_drive_not_the_default(configured_laptop, tmp_path, monkeypatch, capsys):
    drive = tmp_path / "WD" / "dizzy-store"
    drive.mkdir(parents=True)
    monkeypatch.chdir(drive)
    assert cli(["init", "--node-id", "wd", "--role", "cold", "--site", "home", "--limit-bytes", "1GB"]) == 0
    capsys.readouterr()
    assert cli(["found"]) == 0                              # acts on `wd` (here), not on the default laptop
    assert not configured_laptop.exists()
    monkeypatch.chdir(drive.parent)                          # standing BESIDE it (the drive's top) is enough too
    assert cli(["config", "--show"]) == 0
    assert str(drive) in capsys.readouterr().out
