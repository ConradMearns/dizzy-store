"""One daemon per store — and a process that cannot take its port must not have touched the store."""
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import events_of
from dizzy_store.cli import EX_CONFIG, main as cli
from dizzy_store.daemon import Daemon, serve
from dizzy_store.device import Device
from dizzy_store.lock import StoreBusy, StoreLock


@pytest.fixture
def device(tmp_path):
    root = tmp_path / "dev"
    assert cli(["--root", str(root), "init", "--node-id", "d", "--role", "archive", "--site", "lab",
                "--wants", "*", "--limit-bytes", "1GB"]) == 0
    assert cli(["--root", str(root), "found"]) == 0
    return root


def test_a_second_holder_is_refused_and_told_who_has_it(tmp_path):
    (tmp_path / ".store").mkdir()
    with StoreLock(tmp_path / ".store"):
        with pytest.raises(StoreBusy, match=f"pid {os.getpid()}"):
            StoreLock(tmp_path / ".store").acquire()
    StoreLock(tmp_path / ".store").acquire().release()               # free again once released


def test_the_lock_dies_with_its_holder(tmp_path):
    """No stale lock file to clean up after a crash: the kernel lets go the instant the process dies."""
    (tmp_path / ".store").mkdir()
    holder = subprocess.Popen([sys.executable, "-c", f"""
import sys, time
sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'src')!r})
from dizzy_store.lock import StoreLock
StoreLock({str(tmp_path / '.store')!r}).acquire()
print('held', flush=True); time.sleep(60)"""], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(StoreBusy):
            StoreLock(tmp_path / ".store").acquire()
        holder.kill()                                                # a crash, no cleanup
        holder.wait()
        StoreLock(tmp_path / ".store").acquire().release()
    finally:
        holder.kill()


def test_a_busy_store_is_a_configuration_error_for_every_command_that_would_open_it(device, capsys):
    with StoreLock(device / ".store"):
        assert cli(["--root", str(device), "run"]) == EX_CONFIG == 78
        assert "already running" in capsys.readouterr().err


def test_found_will_not_run_beside_a_daemon(tmp_path, capsys):
    root = tmp_path / "dev"
    assert cli(["--root", str(root), "init", "--node-id", "d", "--role", "archive", "--site", "lab",
                "--limit-bytes", "1GB"]) == 0
    with StoreLock(root / ".store"):
        assert cli(["--root", str(root), "found"]) == EX_CONFIG
    assert "already running" in capsys.readouterr().err
    assert Device.load(root)["cluster_id"] is None                   # and it changed nothing
    assert cli(["--root", str(root), "found"]) == 0


def test_a_second_process_never_announces_or_appends_anything(tmp_path):
    """The accident that motivated the lock, as a test: a service runs the store; someone starts it again."""
    root = tmp_path / "dev"
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    number = port.getsockname()[1]
    port.close()
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"devices:\n  d: {{root: {root}, listen: '127.0.0.1:{number}', limit: 1GB}}\n")
    assert cli(["--config", str(cfg), "-d", "d", "init", "--role", "archive", "--site", "lab", "--wants", "*"]) == 0
    assert cli(["--config", str(cfg), "-d", "d", "found"]) == 0
    import dizzy_store
    env = {**os.environ, "NOTIFY_SOCKET": "",
           "PYTHONPATH": str(Path(dizzy_store.__file__).resolve().parents[1]) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    argv = [sys.executable, "-m", "dizzy_store", "--config", str(cfg), "-d", "d", "run"]
    first = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    lines = []
    threading.Thread(target=lambda: [lines.append(l) for l in first.stdout], daemon=True).start()
    try:
        deadline = time.time() + 30
        while not any("announced d" in l for l in lines) and time.time() < deadline:
            time.sleep(0.1)
        assert any("announced d" in l for l in lines), "".join(lines)
        second = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=60)
        assert second.returncode == 78 and "already running" in second.stderr
        assert "announced" not in second.stdout and "starting" not in second.stdout   # it never got as far as starting
        assert first.poll() is None                                  # the first is untouched
    finally:
        first.send_signal(signal.SIGTERM)
        first.wait(timeout=30)


def test_a_process_that_cannot_bind_its_port_has_not_touched_the_store(device):
    daemon = Daemon(Device.load(device))
    before = len(events_of(daemon.node, "node_announced", by="d"))      # `found` announced once already
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    daemon.device.data["listen"] = f"127.0.0.1:{taken.getsockname()[1]}"
    try:
        code = serve(daemon)
    finally:
        taken.close()
    assert code == 78                                                # a config problem: systemd must not respawn it
    assert len(events_of(daemon.node, "node_announced", by="d")) == before, "announced before it was even listening"
    daemon.node.close()
