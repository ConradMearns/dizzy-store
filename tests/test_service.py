"""The systemd user unit that runs a device, and the readiness handshake it relies on."""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest

from dizzy_store import service
from dizzy_store.cli import main as cli
from dizzy_store.daemon import Daemon, serve
from dizzy_store.device import Device
from dizzy_store.http_sim import reserve_port
from dizzy_store.sdnotify import notify


# ── the unit ─────────────────────────────────────────────────────────────────

def test_the_unit_runs_the_named_device_with_the_right_restart_policy():
    text = service.unit_text("/home/conrad/.local/bin/dizzy-store")
    assert "ExecStart=/home/conrad/.local/bin/dizzy-store --device %i run" in text
    assert "Type=notify" in text and "NotifyAccess=main" in text
    assert "ExecReload=/bin/kill -HUP $MAINPID" in text
    assert "Restart=on-failure" in text
    assert "RestartPreventExitStatus=78" in text          # an unmounted drive must not respawn forever
    assert "WantedBy=default.target" in text
    assert "TimeoutStopSec=" in text and "KillMode=mixed" in text


def test_paths_with_spaces_and_percent_signs_survive_systemd_parsing():
    assert 'ExecStart="/opt/my tools/dizzy-store" --device' in service.unit_text("/opt/my tools/dizzy-store")
    assert "ExecStart=/opt/100%%/dizzy-store --device" in service.unit_text("/opt/100%/dizzy-store")


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="systemd-analyze not available")
def test_systemd_accepts_the_unit(tmp_path):
    unit = tmp_path / "dizzy-store@probe.service"
    unit.write_text(service.unit_text(sys.executable))
    result = subprocess.run(["systemd-analyze", "--user", "verify", str(unit)], capture_output=True, text=True)
    assert result.returncode == 0 and result.stderr.strip() == "" and result.stdout.strip() == ""


def test_install_writes_the_template_and_reloads_systemd(tmp_path):
    calls = []
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    path = service.install(sys.executable, env=env, runner=lambda cmd, **kw: calls.append(cmd))
    assert path == tmp_path / "xdg" / "systemd" / "user" / "dizzy-store@.service"
    assert f"ExecStart={sys.executable} --device %i run" in path.read_text()
    assert path.stat().st_mode & 0o777 in (0o644, 0o664)
    if shutil.which("systemctl"):
        assert calls == [["systemctl", "--user", "daemon-reload"]]
    assert service.uninstall(env=env, runner=lambda *a, **k: None) is True
    assert not path.exists() and service.uninstall(env=env) is False


def test_install_refuses_an_executable_that_is_not_there(tmp_path):
    with pytest.raises(FileNotFoundError, match="uv tool install"):
        service.install(str(tmp_path / "nope"), env={"XDG_CONFIG_HOME": str(tmp_path)})
    assert not (tmp_path / "systemd").exists()


def test_the_cli_installs_and_prints(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cli(["service", "print", "--exe", sys.executable]) == 0
    assert f"ExecStart={sys.executable}" in capsys.readouterr().out
    assert cli(["service", "install", "--exe", sys.executable]) == 0
    out = capsys.readouterr().out
    assert "systemctl --user enable --now dizzy-store@NAME" in out
    assert (tmp_path / "systemd" / "user" / "dizzy-store@.service").is_file()
    assert cli(["service", "uninstall"]) == 0


# ── readiness ────────────────────────────────────────────────────────────────

@pytest.fixture
def notify_socket(tmp_path, monkeypatch):
    path = str(tmp_path / "notify.sock")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(path)
    sock.settimeout(5)
    monkeypatch.setenv("NOTIFY_SOCKET", path)
    yield sock
    sock.close()


def test_notify_delivers_a_datagram(notify_socket):
    assert notify("READY=1\nSTATUS=up") is True
    assert notify_socket.recv(1024) == b"READY=1\nSTATUS=up"


def test_notify_is_a_quiet_no_op_outside_systemd(monkeypatch, tmp_path):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert notify("READY=1") is False
    assert notify("READY=1", env={"NOTIFY_SOCKET": str(tmp_path / "nobody-home")}) is False   # never raises


def test_abstract_sockets_are_understood(monkeypatch):
    name = f"@dizzy-store-test-{os.getpid()}"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind("\0" + name[1:])
    sock.settimeout(5)
    try:
        assert notify("READY=1", env={"NOTIFY_SOCKET": name}) is True
        assert sock.recv(64) == b"READY=1"
    finally:
        sock.close()


@pytest.fixture
def device(tmp_path):
    root = tmp_path / "dev"
    assert cli(["--root", str(root), "init", "--node-id", "d", "--role", "archive", "--site", "lab",
                "--wants", "*", "--limit-bytes", "1GB"]) == 0
    assert cli(["--root", str(root), "found"]) == 0
    return root


def test_ready_is_sent_only_once_the_listener_answers(device, notify_socket):
    daemon = Daemon(Device.load(device))
    sock = reserve_port()
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    done = {}
    thread = threading.Thread(target=lambda: done.update(code=serve(daemon, sockets=[sock])), daemon=True)
    thread.start()
    message = notify_socket.recv(1024).decode()
    assert message.startswith("READY=1") and "STATUS=d serving on" in message
    assert httpx.get(f"{url}/peer/cluster", headers={"Authorization": f"Bearer {Device.load(device)['peer_token']}"},
                     timeout=5).status_code == 200      # READY meant it: the listener is already answering
    daemon.server.should_exit = True
    thread.join(timeout=15)
    assert done["code"] == 0
    assert notify_socket.recv(1024) == b"STOPPING=1"
