"""`eject`: stop the device, sync, unmount, power off — in that order — and refuse what is not removable media."""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import make_disk, mountinfo_line
from dizzy_store import eject, volumes
from dizzy_store.volumes import parse_mountinfo


class Runner:
    def __init__(self, active=True, fail=None):
        self.calls, self.active, self.fail = [], active, fail

    def __call__(self, command, **kw):
        self.calls.append(command)
        if command[:3] == ["systemctl", "--user", "is-active"]:
            return subprocess.CompletedProcess(command, 0 if self.active else 3, "", "")
        if self.fail and self.fail in command:
            return subprocess.CompletedProcess(command, 1, "", "Error unmounting: target is busy")
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.fixture
def usb(tmp_path, monkeypatch):
    """A removable USB disk mounted at tmp_path/media/WD, with a fake /sys, and `systemctl` 'installed'."""
    sysfs = tmp_path / "sys"
    ids = make_disk(sysfs, "sda", removable=1)
    mp = tmp_path / "media" / "WD"
    mp.mkdir(parents=True)
    mounts = parse_mountinfo(mountinfo_line(40, ids["1"], str(mp), "ext4", "/dev/sda1"))
    monkeypatch.setattr(volumes, "same_filesystem", lambda a, b: False)
    monkeypatch.setattr(eject.shutil, "which", lambda name: "/usr/bin/" + name)
    return dict(root=mp / "dizzy-store", mounts=mounts, sysfs=sysfs, mp=mp)


def go(usb, runner, name="wd", **kw):
    said = []
    code = eject.run_eject(usb["root"], name, runner=runner, mounts=usb["mounts"], sysfs=usb["sysfs"],
                           proc=kw.pop("proc", usb["sysfs"] / "no-proc"), say=said.append,
                           sync=kw.pop("sync", lambda: said.append("(synced)")), **kw)
    return code, said


def test_it_stops_syncs_unmounts_and_powers_off_in_that_order(usb):
    run = Runner(active=True)
    code, said = go(usb, run)
    assert code == 0
    assert run.calls == [["systemctl", "--user", "is-active", "--quiet", "dizzy-store@wd.service"],
                         ["systemctl", "--user", "stop", "dizzy-store@wd.service"],
                         ["udisksctl", "unmount", "-b", "/dev/sda1"],
                         ["udisksctl", "power-off", "-b", "/dev/sda"]]
    assert said.index("-> sync") < said.index("(synced)") < next(i for i, s in enumerate(said) if "unmount" in s)
    assert any("safe to unplug" in s for s in said)


def test_a_device_that_is_not_running_is_not_stopped(usb):
    run = Runner(active=False)
    assert go(usb, run)[0] == 0
    assert not any(c[:3] == ["systemctl", "--user", "stop"] for c in run.calls)


def test_a_store_run_by_hand_has_no_unit_to_stop(usb):
    run = Runner()
    assert go(usb, run, name=None)[0] == 0
    assert not any(c[0] == "systemctl" for c in run.calls)


def test_no_power_off_leaves_the_disk_spinning(usb):
    run = Runner()
    assert go(usb, run, power_off=False)[0] == 0
    assert not any(c[:2] == ["udisksctl", "power-off"] for c in run.calls)


def test_dry_run_changes_nothing(usb):
    run, synced = Runner(), []
    code, said = go(usb, run, dry_run=True, sync=lambda: synced.append(1))
    assert code == 0 and synced == []
    assert run.calls == [["systemctl", "--user", "is-active", "--quiet", "dizzy-store@wd.service"]]   # only the read-only probe
    assert any("udisksctl unmount" in s for s in said) and any("power-off" in s for s in said)


def test_a_busy_mount_names_what_holds_it(usb, tmp_path):
    proc = tmp_path / "proc"
    for pid, cmd, how in ((4242, b"dizzy-store\0run\0", "cwd"), (777, b"vlc\0movie.mkv\0", "fd"), (9, b"bash\0", None)):
        d = proc / str(pid)
        (d / "fd").mkdir(parents=True)
        (d / "cmdline").write_bytes(cmd)
        os.symlink(usb["mp"] / "dizzy-store" if how == "cwd" else "/home/conrad", d / "cwd")
        if how == "fd":
            os.symlink(usb["mp"] / "movie.mkv", d / "fd" / "3")
    run = Runner(fail="unmount")
    code, said = go(usb, run, proc=proc)
    assert code == 1
    text = "\n".join(said)
    assert "target is busy" in text
    assert "pid 4242 (working directory): dizzy-store run" in text and "pid 777 (open file): vlc movie.mkv" in text
    assert "pid 9" not in text
    assert not any(c[:2] == ["udisksctl", "power-off"] for c in run.calls)       # never power off a mounted disk


def test_a_failed_power_off_still_says_it_is_safe_to_unplug(usb):
    code, said = go(usb, Runner(fail="power-off"))
    assert code == 0 and any("unmounted; unplugging is safe" in s for s in said)


@pytest.mark.parametrize("why, patch", [
    ("system's own filesystem", lambda m: m.setattr(volumes, "same_filesystem", lambda a, b: True)),
])
def test_the_systems_own_filesystem_is_never_ejected(usb, monkeypatch, why, patch):
    patch(monkeypatch)
    run = Runner()
    code, said = go(usb, run)
    assert code == 1 and why in said[0] and run.calls == []


def test_an_internal_disk_is_never_ejected(tmp_path, monkeypatch):
    sysfs = tmp_path / "sys"
    ids = make_disk(sysfs, "sdb", removable=0, bus="sata", rotational=1)
    mp = tmp_path / "mnt" / "data"
    mp.mkdir(parents=True)
    mounts = parse_mountinfo(mountinfo_line(40, ids["1"], str(mp), "ext4", "/dev/sdb1"))
    monkeypatch.setattr(volumes, "same_filesystem", lambda a, b: False)
    run, said = Runner(), []
    assert eject.run_eject(mp, "x", runner=run, mounts=mounts, sysfs=sysfs, say=said.append) == 1
    assert "not removable media" in said[0] and run.calls == []


def test_something_that_is_not_a_block_device_is_refused(tmp_path, monkeypatch):
    mp = tmp_path / "ram"
    mp.mkdir()
    mounts = parse_mountinfo(mountinfo_line(50, "0:44", str(mp), "tmpfs", "tmpfs"))
    monkeypatch.setattr(volumes, "same_filesystem", lambda a, b: False)
    said = []
    assert eject.run_eject(mp, None, runner=Runner(), mounts=mounts, sysfs=tmp_path, say=said.append) == 1
    assert "not removable media" in said[0]


def test_an_unknown_mount_is_refused(tmp_path):
    said = []
    assert eject.run_eject(tmp_path, None, runner=Runner(), mounts=[], sysfs=tmp_path, say=said.append) == 1
    assert "cannot tell" in said[0]
