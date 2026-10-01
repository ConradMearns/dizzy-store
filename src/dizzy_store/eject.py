"""`dizzy-store eject` — take a drive away safely: stop the device, sync, unmount, power off.

Unplugging a drive that a daemon is writing to is how a filesystem gets damaged and how a store ends up
with a blob that was "stored" onto nothing. In order:

  1. stop the device's systemd unit (if one is running) — in-flight transfers stop cleanly and keep their
     verified chunks;
  2. sync;
  3. `udisksctl unmount` — and if something still holds the mount, say WHAT (pid and command), because
     "target is busy" tells a person nothing;
  4. `udisksctl power-off` — a spinning USB disk is spun down and "safe to remove" really is.

It refuses anything that is not removable media: ejecting `/` or an internal disk is never the intent.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from . import volumes

Runner = Callable[..., "subprocess.CompletedProcess"]


def holders(mountpoint: str, proc: str | Path = "/proc") -> list[tuple[int, str, str]]:
    """Processes (that we may inspect) with a working directory or an open file under ``mountpoint``:
    [(pid, command, how)]."""
    prefix = mountpoint.rstrip("/") + "/"
    found = []
    try:
        entries = sorted(p for p in Path(proc).iterdir() if p.name.isdigit())
    except OSError:
        return found
    for entry in entries:
        how = None
        try:
            cwd = os.readlink(entry / "cwd")
            if cwd == mountpoint.rstrip("/") or cwd.startswith(prefix):
                how = "working directory"
            else:
                for fd in (entry / "fd").iterdir():
                    try:
                        if os.readlink(fd).startswith(prefix):
                            how = "open file"
                            break
                    except OSError:
                        continue
        except OSError:
            continue                              # not ours to look at, or already gone
        if how:
            try:
                cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            except OSError:
                cmd = "?"
            found.append((int(entry.name), cmd or "?", how))
    return found


def run_eject(root: Path, name: Optional[str], *, runner: Runner = subprocess.run, mounts=None,
              sysfs: str | Path = "/sys", proc: str | Path = "/proc", say: Callable[[str], None] = print,
              dry_run: bool = False, power_off: bool = True, sync: Callable[[], None] = os.sync) -> int:
    placement = volumes.describe(root, mounts, sysfs)
    mount = placement.mount
    if mount is None:
        say(f"error: cannot tell what {root} is mounted from")
        return 1
    removable = any(d.removable or d.transport == "usb" for d in placement.disks)
    if mount.mountpoint == "/" or volumes.same_filesystem(root, "/"):
        say(f"error: {root} is on the system's own filesystem — there is nothing to eject")
        return 1
    if not mount.source.startswith("/dev/") or not removable:
        say(f"error: {mount.mountpoint} ({mount.source}) is not removable media — refusing to unmount it")
        return 1

    def do(label: str, command: list[str]) -> "subprocess.CompletedProcess":
        say(f"-> {label}: {' '.join(command)}")
        if dry_run:
            return subprocess.CompletedProcess(command, 0, "", "")
        return runner(command, capture_output=True, text=True)

    if name and shutil.which("systemctl"):
        unit = f"dizzy-store@{name}.service"
        active = runner(["systemctl", "--user", "is-active", "--quiet", unit]).returncode == 0
        if active:
            result = do("stop the device", ["systemctl", "--user", "stop", unit])
            if result.returncode != 0:
                say(f"error: could not stop {unit}: {(result.stderr or '').strip()}")
                return 1
    if not dry_run:
        say("-> sync")
        sync()
    result = do("unmount", ["udisksctl", "unmount", "-b", mount.source])
    if result.returncode != 0:
        say(f"error: could not unmount {mount.mountpoint}: {(result.stderr or result.stdout or '').strip()}")
        for pid, cmd, how in holders(mount.mountpoint, proc):
            say(f"  held by pid {pid} ({how}): {cmd[:100]}")
        say("  stop those (a running `dizzy-store run` is the usual one) and try again")
        return 1
    if power_off:
        for disk in placement.disks:
            result = do("power off", ["udisksctl", "power-off", "-b", f"/dev/{disk.name}"])
            if result.returncode != 0:
                say(f"note: could not power off /dev/{disk.name}: {(result.stderr or '').strip()} "
                    "(it is unmounted; unplugging is safe)")
            elif not dry_run:
                say(f"/dev/{disk.name} is powered off — safe to unplug")
    return 0
