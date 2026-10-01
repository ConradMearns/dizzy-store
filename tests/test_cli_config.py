"""The command line's use of the configuration: naming devices, init's safeguards, `config`, `version`."""
import json
from pathlib import Path

import pytest
import yaml

from dizzy_store import cli as cli_module
from dizzy_store.cli import EX_CONFIG, main as cli
from dizzy_store.device import Device, device_file


def config_for(tmp_path, **devices):
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump({"devices": devices}))
    return str(path)


def test_init_by_name_takes_root_node_id_and_limit_from_the_config(tmp_path, capsys):
    cfg = config_for(tmp_path, laptop={"root": str(tmp_path / "laptop"), "limit": "100GB",
                                       "listen": "127.0.0.1:7701", "min_free": "20GB"})
    (tmp_path / "laptop").mkdir()
    assert cli(["--config", cfg, "-d", "laptop", "init", "--role", "archive", "--site", "home", "--wants", "*"]) == 0
    assert "initialized laptop" in capsys.readouterr().out
    device = Device.load(tmp_path / "laptop")
    assert device["node_id"] == "laptop"
    assert device.data["config"]["limit_bytes"] == 100 * 1024 ** 3
    assert device.data["listen"] == "127.0.0.1:7700"     # the machine's `listen` is NOT written to the drive
    assert not any("7701" in line for line in device_file(tmp_path / "laptop").read_text().splitlines())


def test_init_with_nothing_said_means_right_here(tmp_path, monkeypatch, capsys):
    """The drive-carries-its-own-state flow: cd into a directory, `init`, done."""
    here = tmp_path / "drive"
    here.mkdir()
    monkeypatch.chdir(here)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
    assert cli(["init", "--node-id", "wd", "--role", "cold", "--site", "shelf", "--limit-bytes", "1GB"]) == 0
    assert (here / ".store" / "device.json").is_file()


def test_init_needs_a_name_and_a_limit_from_somewhere(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
    assert cli(["--root", str(tmp_path / "a"), "init", "--role", "archive", "--site", "h", "--limit-bytes", "1GB"]) == EX_CONFIG
    assert "name the device" in capsys.readouterr().err
    assert cli(["--root", str(tmp_path / "b"), "init", "--node-id", "b", "--role", "archive", "--site", "h"]) == EX_CONFIG
    assert "no limit" in capsys.readouterr().err
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()


def test_init_will_not_make_a_store_where_a_drive_should_be(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
    args = ["init", "--node-id", "x", "--role", "cold", "--site", "s", "--limit-bytes", "1GB"]
    # the mountpoint's directory is not there at all: the drive is not mounted
    assert cli(["--root", str(tmp_path / "media" / "UUID" / "dizzy-store"), *args]) == EX_CONFIG
    assert "is the drive mounted" in capsys.readouterr().err
    assert not (tmp_path / "media").exists()
    # the mountpoint exists but is just a directory on / (an fstab entry whose drive is absent)
    mnt = tmp_path / "mnt" / "wd"
    mnt.mkdir(parents=True)
    monkeypatch.setattr(cli_module, "_REMOVABLE_PREFIXES", (str(tmp_path / "mnt"),))
    monkeypatch.setattr(cli_module, "_same_filesystem", lambda a, b: True)
    assert cli(["--root", str(mnt / "store"), *args]) == EX_CONFIG
    assert "same filesystem as /" in capsys.readouterr().err
    assert not (mnt / "store").exists()
    assert cli(["--root", str(mnt / "store"), *args, "--force"]) == 0                # a person said so
    monkeypatch.setattr(cli_module, "_same_filesystem", lambda a, b: False)           # a REAL drive is fine
    assert cli(["--root", str(mnt / "store2"), *args]) == 0


def test_the_global_config_flag_and_inits_own_config_flag_coexist(tmp_path):
    cfg = config_for(tmp_path, d={"root": str(tmp_path / "d"), "limit": "1GB"})
    (tmp_path / "d").mkdir()
    assert cli(["--config", cfg, "-d", "d", "init", "--role", "archive", "--site", "h", "--wants", "*",
                "--config", "high_watermark=0.8", "--config", "chunk_size=4MB"]) == 0
    stored = Device.load(tmp_path / "d").data["config"]
    assert stored["high_watermark"] == 0.8 and stored["chunk_size"] == 4 * 1024 ** 2


def test_an_unknown_device_is_a_configuration_error(tmp_path, capsys):
    cfg = config_for(tmp_path, laptop={"root": str(tmp_path / "l")})
    assert cli(["--config", cfg, "-d", "nope", "status"]) == EX_CONFIG
    assert "known: laptop" in capsys.readouterr().err


def test_a_configured_device_whose_drive_is_not_mounted_is_exit_78(tmp_path, capsys):
    cfg = config_for(tmp_path, wd={"root": str(tmp_path / "gone" / "dizzy-store")})
    for command in ("run", "status", "found"):
        assert cli(["--config", cfg, "-d", "wd", command]) == EX_CONFIG
    assert "is not a store device" in capsys.readouterr().err
    assert not (tmp_path / "gone").exists()


def test_config_prints_a_template_and_shows_what_is_in_force(tmp_path, capsys):
    assert cli(["config"]) == 0
    assert "default_device" in capsys.readouterr().out
    cfg = config_for(tmp_path, laptop={"root": str(tmp_path / "l"), "limit": "100GB"})
    assert cli(["--config", cfg, "config", "--show"]) == 0
    out = capsys.readouterr().out
    assert "read" in out and cfg in out and "limit: 107374182400" in out
    assert f"a command run here would act on: 'laptop' at {tmp_path / 'l'}" in out


def test_version_says_what_is_running(capsys):
    assert cli(["version"]) == 0
    out = capsys.readouterr().out
    for key in ("dizzy-store", "source", "commit", "python", "read models", "config files"):
        assert key in out


def test_init_means_here_even_when_a_default_device_is_configured(tmp_path, monkeypatch, capsys):
    """The bug a real portable-drive session found: standing in a drive's folder with a configured
    default_device, `init` must not resolve to that device."""
    cfg = tmp_path / "xdg" / "dizzy-store" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(yaml.safe_dump({"default_device": "laptop",
                                   "devices": {"laptop": {"root": str(tmp_path / "laptop")}}}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / "laptop").mkdir()
    assert cli(["-d", "laptop", "init", "--role", "archive", "--site", "h", "--limit-bytes", "1GB"]) == 0   # named: the laptop
    drive = tmp_path / "drive" / "dizzy-store"
    drive.mkdir(parents=True)
    monkeypatch.chdir(drive)
    assert cli(["init", "--node-id", "wd", "--role", "cold", "--site", "home", "--wants", "*",
                "--limit-bytes", "1GB"]) == 0                                                   # unnamed: right here
    assert Device.load(drive)["node_id"] == "wd" and Device.load(tmp_path / "laptop")["node_id"] == "laptop"
    capsys.readouterr()
    # and a command run from inside or beside that store acts on it, not on the default
    monkeypatch.chdir(tmp_path / "drive")
    assert cli(["config", "--show"]) == 0
    assert f"a command run here would act on: (not in the config) at {drive}" in capsys.readouterr().out
    from dizzy_store.config import resolve
    assert resolve().root == drive
