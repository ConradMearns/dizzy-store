"""The systemd USER unit that runs a device: one template, one instance per device.

    dizzy-store service install                    writes ~/.config/systemd/user/dizzy-store@.service
    systemctl --user enable --now dizzy-store@laptop

The instance name is the device's name in the configuration, so `dizzy-store@wd` runs
`dizzy-store --device wd run` — root, listen address and limits all come from config.yaml, none
from the unit. Linger is what lets it start at boot without a login (`loginctl enable-linger`).

The unit is generated, not shipped as a file: the one thing in it that varies is the path of the
executable (where `uv tool install` put it), and a wrong path is the classic way a unit "installs"
and then never starts.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional

UNIT_NAME = "dizzy-store@.service"

UNIT_TEMPLATE = """\
# Written by `dizzy-store service install` — change the configuration, not this file.
# Instance name = the device's name in the config: dizzy-store@laptop runs `--device laptop`.
[Unit]
Description=dizzy-store device %i
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
# READY=1 is sent once the listener is up (sdnotify.py), so `start` returns when it is true.
Type=notify
NotifyAccess=main
ExecStart={exe} --device %i run
# SIGHUP re-reads the configuration: limits, pacing, cadence and the announced card change live.
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
# 78 = no such store (an unmounted drive, a wrong path): restarting cannot fix it, a person can.
RestartPreventExitStatus=78
TimeoutStartSec=120
# in-flight transfers stop cleanly and their verified chunks are kept
TimeoutStopSec=180
KillMode=mixed
# a backup is not urgent: let the laptop's own work win
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=6
SyslogIdentifier=dizzy-store-%i
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""


def unit_text(exe: str) -> str:
    exe = exe.replace("%", "%%")                # systemd specifiers
    if any(c.isspace() for c in exe):
        exe = f'"{exe}"'
    return UNIT_TEMPLATE.format(exe=exe)


def user_unit_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def default_exe() -> str:
    """The `dizzy-store` that is running now, as an absolute path."""
    found = shutil.which("dizzy-store")
    if found:
        return str(Path(found).absolute())
    return str(Path(sys.argv[0]).resolve())


def exe_warning(exe: str) -> Optional[str]:
    """A console script inside a project virtualenv is not the installed tool: `uv sync` or rebuilding that venv would
    break the service at its next restart, and `dizzy-store update` would not change what it runs. (It is what a bare
    `dizzy-store` resolves to under `uv run`, which is how this gets written by accident.)"""
    parts = Path(exe).parts
    if ".venv" in parts or "venv" in parts:
        return (f"warning: {exe} is inside a project virtualenv, not the installed tool — rebuilding that venv would "
                "break the service at its next restart.\n"
                "         install the tool (`uv tool install --editable ./store`) and run "
                "`~/.local/bin/dizzy-store service install` (not under `uv run`).")
    return None


def install(exe: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
            runner: Callable[..., "subprocess.CompletedProcess"] = subprocess.run) -> Path:
    exe = exe or default_exe()
    if not os.access(exe, os.X_OK):
        raise FileNotFoundError(f"{exe} is not an executable — install the tool first "
                                "(`uv tool install --editable ./store`) or pass --exe PATH")
    directory = user_unit_dir(env)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / UNIT_NAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(unit_text(exe))
    os.replace(tmp, path)
    if shutil.which("systemctl"):
        runner(["systemctl", "--user", "daemon-reload"], check=False)
    return path


def uninstall(env: Optional[Mapping[str, str]] = None,
              runner: Callable[..., "subprocess.CompletedProcess"] = subprocess.run) -> bool:
    path = user_unit_dir(env) / UNIT_NAME
    if not path.exists():
        return False
    path.unlink()
    if shutil.which("systemctl"):
        runner(["systemctl", "--user", "daemon-reload"], check=False)
    return True
