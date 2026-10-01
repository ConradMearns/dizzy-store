"""`dizzy-store doctor [PATH]` — will this place do as a store, and what should be known before it is trusted?

Three kinds of answer, in order of how cheaply they are had:

  FACTS       what the path lives on: filesystem, mount options, the disk underneath (model, USB link
              speed, spinning or not, encrypted or not), free space, whether it shares the operating
              system's filesystem. Read from /proc and /sys; nothing is written.
  CAPABILITIES  what the store depends on, exercised for real in a scratch directory that is always
              removed: write+fsync+read-back, rename over an existing file, hard links, 0600 permissions,
              unicode names, a directory of thousands of entries.
  A BENCHMARK   only with --bench: sustained writes in windows (a drive whose fast cache fills shows as a
              cliff), cold reads, SHA-256 speed, and many small files — the store's real shapes.

Each finding is ok / info / WARN / FAIL with the reason and, where there is one, the fix. The verdict is the
worst of them. A FAIL means do not put a store here; a WARN means know what you are choosing.
"""
from __future__ import annotations

import errno
import hashlib
import os
import shutil
import statistics
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import volumes

LEVELS = ("ok", "info", "warn", "fail")
GiB, MiB = 1024 ** 3, 1024 ** 2

# fstype -> (level, why). Anything not listed is judged by what the capability probes find.
FS_RULES = {
    "vfat": ("fail", "FAT: no permissions, no hard links, and a 4 GiB limit on a single file"),
    "tmpfs": ("fail", "tmpfs lives in RAM and is empty after a reboot"),
    "ramfs": ("fail", "ramfs lives in RAM and is empty after a reboot"),
    "exfat": ("warn", "exFAT has no permissions (the 0600 on device.json cannot protect its tokens), no hard links "
                      "and no symlinks, and is not crash-safe"),
    "ntfs": ("warn", "NTFS through the FUSE/kernel drivers emulates permissions (device.json's 0600 is not "
                     "enforced) and is slow for many small files"),
    "ntfs3": ("warn", "NTFS emulates permissions (device.json's 0600 is not enforced)"),
    "fuseblk": ("warn", "a FUSE-backed filesystem (usually NTFS or exFAT): permissions are emulated"),
    "nfs": ("warn", "a network filesystem: fsync and rename semantics vary, and a dropped link hangs readers"),
    "nfs4": ("warn", "a network filesystem: fsync and rename semantics vary, and a dropped link hangs readers"),
    "cifs": ("warn", "a network filesystem: fsync and rename semantics vary, and a dropped link hangs readers"),
}
GOOD_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "zfs", "bcachefs"}


@dataclass
class Finding:
    level: str
    topic: str
    message: str
    advice: str = ""


@dataclass
class Report:
    path: Path
    facts: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    bench: dict = field(default_factory=dict)

    def add(self, level: str, topic: str, message: str, advice: str = "") -> None:
        assert level in LEVELS, level
        self.findings.append(Finding(level, topic, message, advice))

    @property
    def verdict(self) -> str:
        return max((f.level for f in self.findings), key=LEVELS.index, default="ok")

    def worst(self, topic: str) -> Optional[str]:
        levels = [f.level for f in self.findings if f.topic == topic]
        return max(levels, key=LEVELS.index) if levels else None

    def to_dict(self) -> dict:
        return {"path": str(self.path), "verdict": self.verdict, "facts": self.facts, "bench": self.bench,
                "findings": [vars(f) for f in self.findings]}


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


# ── facts ────────────────────────────────────────────────────────────────────

def _facts(report: Report, real: Path, limit: Optional[int], min_free: Optional[int],
           mounts, sysfs) -> Optional[os.statvfs_result]:
    placement = volumes.describe(real, mounts, sysfs)
    m, disk = placement.mount, placement.disk
    st = os.statvfs(real)
    bs = st.f_frsize
    total, avail = st.f_blocks * bs, st.f_bavail * bs
    reserved = (st.f_bfree - st.f_bavail) * bs
    f = report.facts
    f["path"] = str(real)
    if m:
        f["mounted on"] = f"{m.mountpoint}  ({m.fstype}, {m.options})"
        f["device"] = m.source
    if disk:
        speed = f", USB link {disk.usb_mbps} Mb/s" if disk.usb_mbps else ""
        kind = ("spinning disk" if disk.rotational else "solid state" if disk.rotational is False else "disk")
        f["disk"] = f"{disk.model or disk.name} — {kind}, {disk.transport or 'unknown bus'}{speed}" \
                    f"{', removable' if disk.removable else ''}"
    if placement.layers:
        f["layers"] = " → ".join(placement.layers) + ("  (encrypted)" if placement.encrypted else "")
    f["space"] = f"{human(avail)} available of {human(total)}" + \
                 (f"; {human(reserved)} reserved for root" if reserved else "")
    f["inodes"] = f"{st.f_ffree:,} free of {st.f_files:,}"

    # ── what the facts mean
    fstype = m.fstype if m else ""
    if fstype in FS_RULES:
        level, why = FS_RULES[fstype]
        report.add(level, "filesystem", f"{fstype}: {why}",
                   "format the drive ext4 (a folder on an existing ext4 drive is fine) — never reformat one that "
                   "holds data you want" if level != "ok" else "")
    elif fstype in GOOD_FS:
        report.add("ok", "filesystem", f"{fstype} supports everything the store uses")
    elif fstype:
        report.add("info", "filesystem", f"{fstype}: not one the store has been tried on — the capability checks below decide")
    if m and "ro" in m.options.split(","):
        report.add("fail", "mount", "mounted read-only", "remount read-write (or unmount and mount again normally)")
    if placement.encrypted:
        report.add("ok", "encryption", "encrypted at rest (LUKS)")
    elif disk:
        report.add("info", "encryption", "not encrypted — fine at home; encrypt a drive that will leave the house "
                   "(LUKS), or anyone holding it holds your data")
    shares_os = volumes.same_filesystem(real, "/")
    if shares_os:
        if min_free:
            report.add("info", "shared", f"shares the operating system's filesystem; the {human(min_free)} free-space "
                       "floor is what keeps the store from filling it")
        else:
            report.add("warn", "shared", "shares the operating system's filesystem — a runaway store would fill the "
                       "volume the OS lives on", "set `limit:` and `min_free:` for this device in the config")
    if disk and disk.transport == "usb":
        if disk.usb_mbps and disk.usb_mbps <= 480:
            report.add("warn", "link", f"a USB 2.0 link ({disk.usb_mbps} Mb/s): expect no more than ~35 MB/s",
                       "try a USB 3 port and cable (the link should negotiate 5000 Mb/s or more)")
        elif disk.usb_mbps:
            report.add("ok", "link", f"USB link at {disk.usb_mbps} Mb/s")
        report.add("info", "removable", "behind USB: unplugging without `dizzy-store eject` risks the filesystem; "
                   "the daemon stops itself (exit 74) if its drive vanishes mid-run")
    if disk and disk.rotational:
        report.add("info", "spinning", "a spinning disk: the first access after idle waits several seconds for it to "
                   "spin up, and some drives (SMR) slow sharply once their fast cache fills — `--bench 20GB` "
                   "shows whether this one does")
    if fstype.startswith("ext") and total and reserved / total >= 0.02 and not shares_os:
        usable_gain = max(0, reserved - total // 100)
        report.add("info", "reserved", f"{human(reserved)} ({100 * reserved / total:.1f}%) is held back for root — "
                   "pointless on a data drive",
                   f"`sudo tune2fs -m 1 {m.source}` makes about {human(usable_gain)} usable")

    # ── space against the configured limits
    if limit and avail < limit:
        report.add("warn", "space", f"the {human(limit)} limit is more than the {human(avail)} available")
    if min_free and avail <= min_free:
        report.add("fail", "space", f"only {human(avail)} available — already under the {human(min_free)} floor")
    elif limit and min_free and limit + min_free > avail:
        report.add("warn", "space", f"limit {human(limit)} + floor {human(min_free)} is more than the {human(avail)} "
                   "available: the limit could never be reached without crossing the floor")
    if not limit and not min_free:
        report.add("info", "space", "no `limit` or `min_free` is configured for this device")
    return st


# ── capabilities ─────────────────────────────────────────────────────────────

def _scratch(base: Path, report: Report) -> Optional[Path]:
    work = base / f".dizzy-store-doctor-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    try:
        work.mkdir()                              # never parents: a vanished mount must not be recreated
    except PermissionError:
        report.add("fail", "writable", f"{base} is not writable by this user",
                   f"sudo chown -R $USER {base}   — a drive formatted as root needs this once "
                   "(or format with `mkfs.ext4 -E root_owner=$(id -u):$(id -g)`)")
    except OSError as exc:
        why = "mounted read-only" if exc.errno == errno.EROFS else (exc.strerror or str(exc))
        report.add("fail", "writable", f"cannot write in {base}: {why}")
    else:
        return work
    return None


def _capabilities(work: Path, report: Report, clock: Callable[[], float]) -> None:
    # 1. write, fsync, read back
    data = os.urandom(1 * MiB)
    a = work / "a"
    try:
        fd = os.open(a, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        if hashlib.sha256(a.read_bytes()).digest() != hashlib.sha256(data).digest():
            report.add("fail", "integrity", "bytes read back differ from the bytes written",
                       "this disk, cable or USB bridge is returning wrong data — do not use it")
            return
        report.add("ok", "integrity", "write + fsync + read-back round-trips")
    except OSError as exc:
        report.add("fail", "integrity", f"could not write and sync a file: {exc.strerror or exc}")
        return
    # 2. rename over an existing file (how every blob is placed)
    try:
        b = work / "b"
        b.write_bytes(b"new")
        a.write_bytes(b"old")
        os.replace(b, a)
        if a.read_bytes() == b"new" and not b.exists():
            report.add("ok", "rename", "rename over an existing file replaces it (blobs are placed this way)")
        else:
            report.add("fail", "rename", "rename over an existing file did not replace it")
    except OSError as exc:
        report.add("fail", "rename", f"rename over an existing file failed: {exc.strerror or exc}")
    # 3. permissions: device.json is 0600 because it holds tokens
    try:
        os.chmod(a, 0o600)
        mode = os.stat(a).st_mode & 0o777
        if mode == 0o600:
            report.add("ok", "permissions", "0600 is honoured (device.json's tokens are private)")
        else:
            report.add("warn", "permissions", f"chmod 0600 reads back as {mode:04o}: permissions are not enforced here, "
                       "so anyone who can read the drive can read device.json's tokens")
    except OSError as exc:
        report.add("warn", "permissions", f"chmod failed ({exc.strerror or exc}): permissions are not enforced here")
    # 4. hard links (only `adopt link=true` uses them)
    try:
        os.link(a, work / "linked")
        if os.stat(a).st_nlink == 2:
            report.add("ok", "hardlinks", "hard links work (`adopt link=true` can save space)")
        else:
            report.add("warn", "hardlinks", "hard links did not take (`adopt link=true` would copy)")
    except OSError as exc:
        report.add("warn", "hardlinks", f"hard links are not supported ({exc.strerror or exc}); "
                   "adoption must copy — fine, just not free")
    # 5. names
    try:
        (work / "Case").write_bytes(b"1")
        (work / "case").write_bytes(b"2")
        names = set(os.listdir(work))
        if {"Case", "case"} <= names:
            report.add("ok", "names", "file names are case-sensitive")
        else:
            report.add("info", "names", "file names are case-INSENSITIVE (blob names are lowercase hex, so harmless)")
    except OSError as exc:
        report.add("warn", "names", f"could not create differently-cased names: {exc.strerror or exc}")
    try:
        (work / "é日本🙂.bin").write_bytes(b"x")
        report.add("ok", "unicode", "unicode file names work")
    except OSError as exc:
        report.add("warn", "unicode", f"unicode file names fail ({exc.strerror or exc})")
    # 6. a directory with thousands of entries (a 2-level shard holds many blobs per directory)
    many = work / "many"
    many.mkdir()
    start = clock()
    try:
        for i in range(1500):
            (many / f"{i:06d}").touch()
        listed = len(os.listdir(many))
        elapsed = clock() - start
        rate = 1500 / elapsed if elapsed > 0 else float("inf")
        level = "ok" if elapsed < 10 and listed == 1500 else "warn"
        report.add(level, "metadata", f"created and listed 1,500 files in {elapsed:.2f}s ({rate:,.0f}/s)",
                   "" if level == "ok" else "slow metadata: walks and scrubs over many blobs will be slow here")
        report.facts["metadata"] = f"{rate:,.0f} file creations/s"
    except OSError as exc:
        report.add("warn", "metadata", f"could not create 1,500 files in one directory: {exc.strerror or exc}")


# ── benchmark ────────────────────────────────────────────────────────────────

def _cliff(rates: list[float]) -> Optional[tuple[float, float]]:
    """(early speed, late speed) if sustained writes COLLAPSED, else None: the typical (median) speed of
    the last quarter of the windows under half that of the first quarter (needs 8+ windows). Medians, not
    minimums: one stalled window (a background indexer, a power-management blip) is not a collapse — a drive
    whose fast cache has filled stays slow."""
    if len(rates) < 8:
        return None
    quarter = max(2, len(rates) // 4)
    head = statistics.median(rates[:quarter])
    tail = statistics.median(rates[-quarter:])
    return (head, tail) if tail < 0.5 * head else None


def _bench(work: Path, nbytes: int, report: Report, clock: Callable[[], float],
           say: Callable[[str], None]) -> None:
    window = min(nbytes, max(64 * MiB, nbytes // 32))
    pool = os.urandom(32 * MiB)                   # random, generated once so the disk is what is measured
    path = work / "bench.bin"
    say(f"  writing {human(nbytes)} in {human(window)} windows (fsync after each)…")
    windows: list[tuple[int, float]] = []
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        written, offset = 0, 0
        while written < nbytes:
            t0, in_window = clock(), 0
            while in_window < window and written < nbytes:
                n = min(4 * MiB, nbytes - written, window - in_window)
                offset = (offset + 977 * 1024) % (len(pool) - n)         # a different slice each time
                os.write(fd, memoryview(pool)[offset:offset + n])
                written += n
                in_window += n
            os.fsync(fd)
            windows.append((in_window, clock() - t0))
    finally:
        os.close(fd)
    rates = [b / s / 1e6 for b, s in windows if s > 0]
    total_s = sum(s for _, s in windows)
    bench = report.bench
    bench["write_mb_s"] = round(nbytes / total_s / 1e6, 1) if total_s else 0
    bench["write_windows_mb_s"] = [round(r, 1) for r in rates]
    cliff = _cliff(rates)
    if cliff:
        head, tail = cliff
        report.add("warn", "sustained-writes",
                   f"write speed fell from ~{head:.0f} MB/s to ~{tail:.0f} MB/s partway through — typical of "
                   "a drive whose fast cache filled (SMR)",
                   "a long first copy will crawl once the cache is spent; the store paces itself, so it still "
                   "finishes — just plan for the slow rate")
    # cold read + hash, timed separately: is the disk or the CPU the limit?
    try:
        rfd = os.open(path, os.O_RDONLY)
        try:
            os.posix_fadvise(rfd, 0, 0, os.POSIX_FADV_DONTNEED)         # drop the (clean, fsynced) cache
            read_s = hash_s = 0.0
            digest = hashlib.sha256()
            while True:
                t0 = clock()
                block = os.read(rfd, 4 * MiB)
                t1 = clock()
                if not block:
                    break
                digest.update(block)
                read_s += t1 - t0
                hash_s += clock() - t1
        finally:
            os.close(rfd)
        bench["read_mb_s"] = round(nbytes / read_s / 1e6, 1) if read_s else 0
        bench["hash_mb_s"] = round(nbytes / hash_s / 1e6, 1) if hash_s else 0
    except (OSError, AttributeError):
        pass
    path.unlink(missing_ok=True)
    # the store's other shape: many small files, each written to a temp name, synced and renamed
    small = work / "small"
    small.mkdir()
    start = clock()
    body = pool[:64 * 1024]
    count = 200
    for i in range(count):
        tmp = small / f"{i}.part"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            os.write(fd, body)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, small / str(i))
    bench["small_files_per_s"] = round(count / max(clock() - start, 1e-9), 1)
    if "read_mb_s" in bench and "hash_mb_s" in bench:
        limit = "the disk" if bench["read_mb_s"] < bench["hash_mb_s"] else "the CPU"
        report.add("info", "throughput",
                   f"write {bench['write_mb_s']} MB/s · cold read {bench['read_mb_s']} MB/s · SHA-256 "
                   f"{bench['hash_mb_s']} MB/s · {bench['small_files_per_s']} small files/s — verifying (scrub) is "
                   f"limited by {limit}")
        report.add("info", "estimate", f"scrubbing 32 GiB would take about "
                   f"{32 * 1024 / max(min(bench['read_mb_s'], bench['hash_mb_s']), 1) / 60:.0f} minutes")


# ── SMART ────────────────────────────────────────────────────────────────────

def _smart(disk: volumes.Disk, report: Report, run: Callable[..., "subprocess.CompletedProcess"]) -> None:
    exe = shutil.which("smartctl")
    if not exe:
        report.add("info", "health", "smartctl is not installed, so the drive's own health report was not read",
                   "sudo apt install smartmontools   (then `sudo smartctl -H /dev/" + disk.name + "`)")
        return
    for extra in ([], ["-d", "sat"]):             # many USB enclosures need the SAT pass-through
        try:
            result = run([exe, "-H", *extra, f"/dev/{disk.name}"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        out = (result.stdout or "") + (result.stderr or "")
        if "PASSED" in out or "OK" in out.split("SMART overall-health", 1)[-1][:60]:
            report.add("ok", "health", "SMART overall health: PASSED")
            return
        if "FAILED" in out:
            report.add("fail", "health", "SMART overall health: FAILED", "this drive is dying — copy off what matters now")
            return
        if "Permission denied" in out or "Operation not permitted" in out:
            report.add("info", "health", "reading SMART needs root", f"sudo smartctl -H /dev/{disk.name}")
            return
    report.add("info", "health", "SMART could not be read through this enclosure")


# ── the whole probe ──────────────────────────────────────────────────────────

def probe(path: str | Path, *, bench_bytes: int = 0, limit: Optional[int] = None, min_free: Optional[int] = None,
          mounts=None, sysfs: str | Path = "/sys", smart: bool = True,
          run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
          clock: Callable[[], float] = time.perf_counter, say: Callable[[str], None] = lambda _: None) -> Report:
    real = Path(os.path.realpath(path))
    report = Report(real)
    if not real.exists():
        report.add("fail", "path", f"{real} does not exist",
                   "create it (`mkdir`), or — for a drive — mount it first; the store never creates the path above it")
        return report
    if not real.is_dir():
        report.add("fail", "path", f"{real} is not a directory")
        return report
    _facts(report, real, limit, min_free, mounts, sysfs)
    disk = volumes.describe(real, mounts, sysfs).disk
    work = _scratch(real, report)
    if work is not None:
        try:
            _capabilities(work, report, clock)
            if bench_bytes:
                avail = os.statvfs(real).f_bavail * os.statvfs(real).f_frsize
                if avail - bench_bytes < max(256 * MiB, bench_bytes // 10, min_free or 0):
                    report.add("fail", "bench", f"not enough room to benchmark {human(bench_bytes)} here without "
                               f"crossing the floor ({human(avail)} available)", "pick a smaller --bench size")
                elif report.worst("integrity") == "fail":
                    report.add("info", "bench", "skipped: the integrity check failed")
                else:
                    _bench(work, bench_bytes, report, clock, say)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    if smart and disk is not None:
        _smart(disk, report, run)
    return report


MARKS = {"ok": "[ ok ]", "info": "[info]", "warn": "[WARN]", "fail": "[FAIL]"}


def render(report: Report) -> str:
    lines = [f"dizzy-store doctor: {report.path}", ""]
    width = max((len(k) for k in report.facts), default=0)
    lines += [f"  {k:<{width}}  {v}" for k, v in report.facts.items()]
    if report.facts:
        lines.append("")
    for f in report.findings:
        lines.append(f"{MARKS[f.level]} {f.message}")
        if f.advice:
            lines.append(f"       → {f.advice}")
    lines.append("")
    verdict = {"ok": "fit for a store", "info": "fit for a store",
               "warn": "usable — read the warnings", "fail": "NOT fit for a store as it is"}[report.verdict]
    lines.append(f"verdict: {verdict}")
    return "\n".join(lines)
