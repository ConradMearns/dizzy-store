"""SIGHUP: re-read the configuration, apply what can change live, refuse what is broken."""
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

from conftest import events_of
from dizzy_store.cli import main as cli
from dizzy_store.config import ConfigError, DeviceSettings, Loaded, Resolved, StoreConfig
from dizzy_store.daemon import Daemon
from dizzy_store.device import Device


@pytest.fixture
def rig(tmp_path):
    """A daemon whose 'configuration' is a variable the test can change."""
    root = tmp_path / "dev"
    assert cli(["--root", str(root), "init", "--node-id", "d", "--role", "archive", "--site", "lab",
                "--wants", "*", "--limit-bytes", "1GB", "--endpoint", "http://on-the-drive:1"]) == 0
    assert cli(["--root", str(root), "found"]) == 0
    state = {"settings": DeviceSettings(), "calls": 0}

    def reresolve():
        state["calls"] += 1
        if isinstance(state["settings"], Exception):
            raise state["settings"]
        return Resolved(root, "d", state["settings"], Loaded(StoreConfig(), [], []))

    daemon = Daemon(Device.load(root), reresolve=reresolve)
    daemon.announce()
    yield daemon, state
    daemon.node.close()


def test_limits_the_floor_and_pacing_change_live(rig):
    daemon, state = rig
    state["settings"] = DeviceSettings(limit="5GB", min_free="2GB",
                                       settings={"max_dispatch_per_event": 3, "high_watermark": 0.8},
                                       pacing={"max_bytes_per_sec": "10MB"})
    changed = daemon.reload()
    env = daemon.node.env_store
    assert env.limit_bytes == 5 * 1024 ** 3 and env.min_free_bytes == 2 * 1024 ** 3
    assert env.max_dispatch_per_event == 3 and env.high_watermark == 0.8
    assert env.max_bytes_per_sec == 10 * 1024 ** 2
    assert {"limit_bytes=5368709120", "min_free_bytes=2147483648"} <= set(changed)


def test_a_setting_taken_out_of_the_file_returns_to_what_the_drive_says(rig):
    daemon, state = rig
    state["settings"] = DeviceSettings(limit="5GB", min_free="2GB")
    daemon.reload()
    state["settings"] = DeviceSettings()
    daemon.reload()
    env = daemon.node.env_store
    assert env.limit_bytes == 1024 ** 3                  # the drive's own value, from `init`
    assert env.min_free_bytes == 0                       # no floor: the default


def test_a_nothing_changed_reload_says_so(rig, caplog):
    daemon, state = rig
    with caplog.at_level(logging.INFO, logger="dizzy_store"):
        assert daemon.reload() == []
    assert "nothing changed" in caplog.text


def test_a_bad_configuration_is_refused_and_the_running_one_kept(rig, caplog):
    daemon, state = rig
    state["settings"] = DeviceSettings(limit="5GB")
    daemon.reload()
    state["settings"] = ConfigError("devices.d.limt: Extra inputs are not permitted")
    with caplog.at_level(logging.ERROR, logger="dizzy_store"):
        assert daemon.reload() == []
    assert "reload refused" in caplog.text and "limt" in caplog.text
    assert daemon.node.env_store.limit_bytes == 5 * 1024 ** 3       # unchanged: a typo cannot take a backup off the air
    assert daemon.device.settings.limit == 5 * 1024 ** 3


def test_a_changed_card_is_announced(rig):
    daemon, state = rig
    before = len(events_of(daemon.node, "node_announced", by="d"))
    state["settings"] = DeviceSettings(endpoints=["http://new-address:9"])
    assert "announced card" in daemon.reload()
    announced = events_of(daemon.node, "node_announced", by="d")
    assert len(announced) == before + 1 and announced[-1]["endpoints"] == ["http://new-address:9"]
    before = len(announced)
    daemon.reload()                                       # the same again: no new announcement
    assert len(events_of(daemon.node, "node_announced", by="d")) == before


def test_seeds_and_cadence_change_live(rig):
    daemon, state = rig
    state["settings"] = DeviceSettings(seeds={"nas": "http://nas:1"}, intervals={"sync_s": 4})
    changed = daemon.reload()
    assert "seeds" in changed and "intervals" in changed
    assert daemon.node.peers._seeds == {"nas": "http://nas:1"}
    assert daemon.device["intervals"]["sync_s"] == 4


def test_listen_and_root_changes_wait_for_a_restart(rig, caplog, tmp_path):
    daemon, state = rig
    before = daemon.device["listen"]
    state["settings"] = DeviceSettings(listen="127.0.0.1:9999")
    with caplog.at_level(logging.WARNING, logger="dizzy_store"):
        daemon.reload()
    assert "restart to use it" in caplog.text
    assert daemon.device["listen"] == before             # still what the socket is bound to


def test_a_daemon_with_no_way_to_re_resolve_ignores_sighup(rig):
    daemon, state = rig
    daemon.reresolve = None
    assert daemon.reload() == []


def test_the_loop_notices_a_reload_request(rig):
    daemon, state = rig
    thread = threading.Thread(target=daemon.loop, daemon=True)
    thread.start()
    time.sleep(0.3)
    state["settings"] = DeviceSettings(limit="7GB")
    daemon.request_reload()
    deadline = time.time() + 10
    while daemon.node.env_store.limit_bytes != 7 * 1024 ** 3 and time.time() < deadline:
        time.sleep(0.1)
    daemon.stop.set()
    thread.join(timeout=10)
    assert daemon.node.env_store.limit_bytes == 7 * 1024 ** 3


# ── the real signal, a real process ──────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sighup_reloads_a_running_process_and_sigterm_stops_it_cleanly(tmp_path):
    root = tmp_path / "dev"
    cfg = tmp_path / "config.yaml"
    port = free_port()

    def write(limit):
        cfg.write_text(yaml.safe_dump({"devices": {"d": {"root": str(root), "listen": f"127.0.0.1:{port}",
                                                          "limit": limit}}}))
    write("1GB")
    assert cli(["--config", str(cfg), "-d", "d", "init", "--role", "archive", "--site", "lab", "--wants", "*"]) == 0
    assert cli(["--config", str(cfg), "-d", "d", "found"]) == 0
    import dizzy_store
    src = str(Path(dizzy_store.__file__).resolve().parents[1])          # the package THIS test is testing —
    proc = subprocess.Popen([sys.executable, "-m", "dizzy_store", "--config", str(cfg), "-d", "d", "run"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,     # not whichever copy
                            env={**os.environ, "NOTIFY_SOCKET": "",                         # the environment has installed
                                 "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")})
    lines = []
    reader = threading.Thread(target=lambda: [lines.append(l) for l in proc.stdout], daemon=True)
    reader.start()
    try:
        deadline = time.time() + 30
        while not any("announced d" in l for l in lines) and time.time() < deadline:
            time.sleep(0.1)
        assert any("announced d" in l for l in lines), "".join(lines)
        write("9GB")
        proc.send_signal(signal.SIGHUP)
        deadline = time.time() + 15
        while not any("reloaded the configuration" in l for l in lines) and time.time() < deadline:
            time.sleep(0.1)
        assert any("limit_bytes=" + str(9 * 1024 ** 3) in l for l in lines), "".join(lines)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == 0                  # a clean stop: systemd calls this success
    finally:
        if proc.poll() is None:
            proc.kill()
