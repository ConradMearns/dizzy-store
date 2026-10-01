"""`doctor`: facts, capabilities, space, benchmark and health — each judged, none touching what it should not."""
import errno
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import make_disk, make_dm, mountinfo_line
from dizzy_store import doctor, volumes
from dizzy_store.cli import main as cli
from dizzy_store.volumes import parse_mountinfo

GiB = 1024 ** 3


@pytest.fixture
def as_ext4(tmp_path, monkeypatch):
    """tmp_path may be tmpfs (it is on many machines) — which doctor rightly refuses. Present it as ext4:
    the mount table a probe reads is replaced, on a device number that exists in no real /sys."""
    mounts = parse_mountinfo(mountinfo_line(40, "250:99", str(tmp_path), "ext4", "/dev/fake1"))
    monkeypatch.setattr(volumes, "read_mounts", lambda *a: mounts)
    return mounts


def levels(report, topic):
    return [f.level for f in report.findings if f.topic == topic]


def probe_on(tmp_path, fstype="ext4", options="rw,relatime", disk=None, **kw):
    """Probe tmp_path as though it were mounted from a disk with this filesystem."""
    sysfs = tmp_path / "sys"
    ids = make_disk(sysfs, "sda", **(disk or {}))
    mounts = parse_mountinfo(mountinfo_line(40, ids["1"], str(tmp_path), fstype, "/dev/sda1", options=options))
    store = tmp_path / "place"
    store.mkdir()
    kw.setdefault("smart", False)
    return doctor.probe(store, mounts=mounts, sysfs=sysfs, **kw), store


# ── the place ────────────────────────────────────────────────────────────────

def test_a_path_that_is_not_there_is_a_failure_with_the_fix(tmp_path):
    report = doctor.probe(tmp_path / "gone", smart=False)
    assert report.verdict == "fail" and "does not exist" in report.findings[0].message
    assert "mount it first" in report.findings[0].advice
    assert not (tmp_path / "gone").exists()                           # the probe never creates the path
    f = tmp_path / "file"
    f.write_text("x")
    assert "not a directory" in doctor.probe(f, smart=False).findings[0].message


def test_a_healthy_directory_passes_every_capability_and_leaves_nothing_behind(tmp_path, as_ext4):
    work = tmp_path / "store"
    work.mkdir()
    report = doctor.probe(work, smart=False)
    for topic in ("integrity", "rename", "permissions", "hardlinks", "names", "unicode", "metadata"):
        assert report.worst(topic) in ("ok", "info"), (topic, [f.message for f in report.findings if f.topic == topic])
    assert report.verdict in ("ok", "info", "warn")                   # (warn: shares the OS volume, perhaps)
    assert list(work.iterdir()) == []                                  # the scratch directory is gone


def test_the_scratch_directory_is_removed_even_when_a_check_blows_up(tmp_path, monkeypatch):
    work = tmp_path / "store"
    work.mkdir()
    monkeypatch.setattr(doctor, "_capabilities", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        doctor.probe(work, smart=False)
    assert list(work.iterdir()) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_an_unwritable_root_says_how_to_fix_it(tmp_path):
    """A drive formatted by root and mounted for you: exactly what a fresh ext4 volume looks like."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        report = doctor.probe(locked, smart=False)
    finally:
        locked.chmod(0o755)
    assert report.verdict == "fail"
    (finding,) = [f for f in report.findings if f.topic == "writable"]
    assert "chown" in finding.advice and "root_owner" in finding.advice


def test_a_read_only_filesystem_is_a_failure(tmp_path, monkeypatch):
    real = Path.mkdir

    def refuse(self, *a, **k):
        if ".dizzy-store-doctor" in self.name:
            raise OSError(errno.EROFS, "Read-only file system")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "mkdir", refuse)
    report = doctor.probe(tmp_path, smart=False)
    assert any(f.topic == "writable" and "read-only" in f.message for f in report.findings)


# ── what the filesystem is ───────────────────────────────────────────────────

@pytest.mark.parametrize("fstype, level", [("ext4", "ok"), ("xfs", "ok"), ("btrfs", "ok"), ("vfat", "fail"),
                                           ("exfat", "warn"), ("ntfs3", "warn"), ("fuseblk", "warn"),
                                           ("tmpfs", "fail"), ("nfs4", "warn")])
def test_the_filesystem_is_judged(tmp_path, fstype, level):
    report, _ = probe_on(tmp_path, fstype=fstype)
    assert report.worst("filesystem") == level
    assert report.facts["mounted on"].endswith(f"({fstype}, rw,relatime)")


def test_a_ram_filesystem_is_never_fit_for_a_store(tmp_path, monkeypatch):
    mounts = parse_mountinfo(mountinfo_line(40, "250:99", str(tmp_path), "tmpfs", "tmpfs"))
    monkeypatch.setattr(volumes, "read_mounts", lambda *a: mounts)
    report = doctor.probe(tmp_path, smart=False)
    assert report.verdict == "fail" and "RAM" in [f.message for f in report.findings if f.topic == "filesystem"][0]


def test_an_unknown_filesystem_is_left_to_the_capability_checks(tmp_path):
    assert probe_on(tmp_path, fstype="weirdfs")[0].worst("filesystem") == "info"


def test_a_read_only_mount_is_a_failure(tmp_path):
    report, _ = probe_on(tmp_path, options="ro,relatime")
    assert report.worst("mount") == "fail"


def test_the_disk_is_described_and_a_slow_usb_link_is_flagged(tmp_path):
    fast, _ = probe_on(tmp_path / "a", disk=dict(usb_speed=5000)) if (tmp_path / "a").mkdir() is None else (None, None)
    assert "USB link 5000 Mb/s" in fast.facts["disk"] and "spinning disk" in fast.facts["disk"]
    assert fast.worst("link") == "ok" and fast.worst("spinning") == "info" and fast.worst("removable") == "info"
    (tmp_path / "b").mkdir()
    slow, _ = probe_on(tmp_path / "b", disk=dict(usb_speed=480))
    assert slow.worst("link") == "warn" and "USB 3" in [f for f in slow.findings if f.topic == "link"][0].advice


def test_encryption_is_reported_either_way(tmp_path):
    sysfs = tmp_path / "sys"
    make_disk(sysfs, "nvme0n1", rotational=0, bus="nvme", parts=("3",), major=259)
    part = next((sysfs / "devices/pci0000:00/0000:00:1d.0/nvme/nvme0").glob("nvme0n1/nvme0n13")).resolve()
    make_dm(sysfs, "dm-0", "252:0", "CRYPT-LUKS2-abc", part)
    mounts = parse_mountinfo(mountinfo_line(22, "252:0", str(tmp_path), "ext4", "/dev/mapper/crypt"))
    work = tmp_path / "w"
    work.mkdir()
    encrypted = doctor.probe(work, mounts=mounts, sysfs=sysfs, smart=False)
    assert encrypted.worst("encryption") == "ok" and "dm-crypt" in encrypted.facts["layers"]
    plain, _ = probe_on(tmp_path / "x") if (tmp_path / "x").mkdir() is None else (None, None)
    assert "not encrypted" in [f.message for f in plain.findings if f.topic == "encryption"][0]


def test_sharing_the_operating_systems_filesystem_is_a_warning_unless_a_floor_protects_it(tmp_path, monkeypatch):
    monkeypatch.setattr(volumes, "same_filesystem", lambda a, b: True)
    assert probe_on(tmp_path / "1", ) if (tmp_path / "1").mkdir() is None else None
    (tmp_path / "2").mkdir()
    bare, _ = probe_on(tmp_path / "2")
    assert bare.worst("shared") == "warn"
    (tmp_path / "3").mkdir()
    floored, _ = probe_on(tmp_path / "3", min_free=20 * GiB)
    assert floored.worst("shared") == "info"


def test_reserved_blocks_on_a_data_drive_are_pointed_out(tmp_path, monkeypatch):
    real = os.statvfs

    def fake(path):
        st = real(path)
        total = 1000 * 1024 * 1024 * 1024 // st.f_frsize
        return os.statvfs_result((st.f_bsize, st.f_frsize, total, int(total * 0.60), int(total * 0.55), st.f_files,
                                  st.f_ffree, st.f_favail, st.f_flag, st.f_namemax))
    monkeypatch.setattr(doctor.os, "statvfs", fake)
    monkeypatch.setattr(volumes, "same_filesystem", lambda a, b: False)
    report, _ = probe_on(tmp_path)
    (note,) = [f for f in report.findings if f.topic == "reserved"]
    assert "5.0%" in note.message and "tune2fs -m 1 /dev/sda1" in note.advice


# ── space against the limits ─────────────────────────────────────────────────

def test_limits_are_checked_against_the_space_available(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    huge = 10 ** 18
    assert doctor.probe(work, smart=False, limit=huge).worst("space") == "warn"
    assert doctor.probe(work, smart=False, min_free=huge).worst("space") == "fail"
    both = doctor.probe(work, smart=False, limit=huge // 2, min_free=huge // 4)
    assert "could never be reached" in " ".join(f.message for f in both.findings if f.topic == "space") or \
        both.worst("space") in ("warn", "fail")
    assert doctor.probe(work, smart=False).worst("space") == "info"                 # nothing configured
    assert doctor.probe(work, smart=False, limit=1024, min_free=1024).worst("space") != "fail"


# ── capabilities that can fail ───────────────────────────────────────────────

def test_unsupported_hard_links_and_ignored_permissions_are_warnings(tmp_path, monkeypatch):
    work = tmp_path / "w"
    work.mkdir()
    monkeypatch.setattr(doctor.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EPERM, "nope")))
    real_chmod = os.chmod
    monkeypatch.setattr(doctor.os, "chmod", lambda p, m, **k: real_chmod(p, 0o755))      # exFAT: always 0755
    report = doctor.probe(work, smart=False)
    assert report.worst("hardlinks") == "warn" and "adoption must copy" in \
        [f.message for f in report.findings if f.topic == "hardlinks"][0]
    assert report.worst("permissions") == "warn" and "0755" in \
        [f.message for f in report.findings if f.topic == "permissions"][0]
    assert report.worst("integrity") == "ok"


def test_a_filesystem_that_corrupts_what_it_stores_is_a_hard_failure(tmp_path, monkeypatch):
    work = tmp_path / "w"
    work.mkdir()
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: real(self)[:-1] + b"X" if self.name == "a" else real(self))
    report = doctor.probe(work, smart=False)
    assert report.worst("integrity") == "fail" and report.verdict == "fail"
    assert "do not use it" in [f.advice for f in report.findings if f.topic == "integrity"][0]


def test_a_failed_rename_is_reported(tmp_path, monkeypatch):
    work = tmp_path / "w"
    work.mkdir()
    monkeypatch.setattr(doctor.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EXDEV, "no")))
    assert doctor.probe(work, smart=False).worst("rename") == "fail"


# ── benchmark ────────────────────────────────────────────────────────────────

def test_a_small_benchmark_reports_every_shape_and_cleans_up(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    said = []
    report = doctor.probe(work, bench_bytes=3 * 1024 * 1024, smart=False, say=said.append)
    assert set(report.bench) >= {"write_mb_s", "write_windows_mb_s", "read_mb_s", "hash_mb_s", "small_files_per_s"}
    assert all(v > 0 for k, v in report.bench.items() if k != "write_windows_mb_s")
    assert said and "writing 3.0 MiB" in said[0]
    assert "limited by" in [f.message for f in report.findings if f.topic == "throughput"][0]
    assert any(f.topic == "estimate" for f in report.findings)
    assert list(work.iterdir()) == []


def test_the_benchmark_refuses_what_would_cross_the_floor(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    free = os.statvfs(work).f_bavail * os.statvfs(work).f_frsize
    report = doctor.probe(work, bench_bytes=free, smart=False)
    assert report.worst("bench") == "fail" and "not enough room" in \
        [f.message for f in report.findings if f.topic == "bench"][0]
    assert "write_mb_s" not in report.bench and list(work.iterdir()) == []


def test_a_collapse_in_sustained_writes_is_recognised():
    steady = [140.0] * 16
    smr = [140.0] * 6 + [135.0, 120.0, 30.0, 25.0, 28.0, 22.0, 31.0, 26.0, 24.0, 29.0]
    assert doctor._cliff(steady) is None
    head, tail = doctor._cliff(smr)
    assert head > 130 and tail < 30
    assert doctor._cliff([140, 20, 20, 20]) is None                   # too few windows to call it
    assert doctor._cliff([100.0] * 6 + [60.0, 55.0, 58.0, 52.0]) is None   # a dip, not a collapse
    assert doctor._cliff([140.0] * 15 + [20.0]) is None                     # one stalled window is not a collapse
    assert doctor._cliff([60.0] * 7 + [25.0] + [60.0] * 8) is None
    assert doctor._cliff([140.0] * 8 + [30.0] * 8) is not None              # sustained: it is


# ── health ───────────────────────────────────────────────────────────────────

def fake_run(output, code=0):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, output, "")


def disk_for(tmp_path):
    ids = make_disk(tmp_path / "s", "sda")
    mounts = parse_mountinfo(mountinfo_line(40, ids["1"], str(tmp_path), "ext4", "/dev/sda1"))
    return volumes.describe(tmp_path, mounts, tmp_path / "s").disk


@pytest.mark.parametrize("output, level", [
    ("SMART overall-health self-assessment test result: PASSED", "ok"),
    ("SMART overall-health self-assessment test result: FAILED!", "fail"),
    ("Smartctl open device: /dev/sda failed: Permission denied", "info"),
    ("something unexpected", "info"),
])
def test_smart_output_is_judged(tmp_path, monkeypatch, output, level):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/sbin/smartctl")
    report = doctor.Report(tmp_path)
    doctor._smart(disk_for(tmp_path), report, fake_run(output))
    assert report.worst("health") == level


def test_a_missing_smartctl_says_how_to_get_it(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    report = doctor.Report(tmp_path)
    doctor._smart(disk_for(tmp_path), report, fake_run(""))
    assert "smartmontools" in report.findings[0].advice


# ── rendering and the command ────────────────────────────────────────────────

def test_render_and_json(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    report = doctor.probe(work, smart=False)
    text = doctor.render(report)
    assert text.startswith("dizzy-store doctor:") and "verdict:" in text and "[ ok ]" in text
    assert json.loads(json.dumps(report.to_dict()))["verdict"] == report.verdict


def test_the_command_probes_a_path_and_exits_zero_or_one(tmp_path, capsys, as_ext4):
    work = tmp_path / "w"
    work.mkdir()
    assert cli(["doctor", str(work), "--no-smart"]) == 0
    assert "verdict:" in capsys.readouterr().out
    assert cli(["doctor", str(work), "--no-smart", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["path"] == str(work.resolve())
    assert cli(["doctor", str(tmp_path / "gone"), "--no-smart"]) == 1


def test_the_command_uses_the_devices_limits_when_probing_its_root(tmp_path, capsys, as_ext4):
    import yaml
    root = tmp_path / "store"
    root.mkdir()
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump({"devices": {"d": {"root": str(root), "limit": 10 ** 18}}}))
    assert cli(["--config", str(cfg), "-d", "d", "doctor", "--no-smart", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert any(f["topic"] == "space" and "limit" in f["message"] for f in report["findings"])
