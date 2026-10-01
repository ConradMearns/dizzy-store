"""The free-space floor (principle 11): the one pressure rule, the disk observation, and what a
refused upload looks like."""
import os

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from conftest import ARCHIVE, events_of
from dizzy_store.cli import main as cli
from dizzy_store.daemon import Daemon
from dizzy_store.device import Device
from dizzy_store.node import RealDisk
from dizzy_store.sim import SimDisk
from storeutil import FLOOR_MARGIN, OutOfSpace, capacity_pressure, free_bytes

KB = 1024


def store(limit=100 * KB, floor=0, high=0.9, low=0.7):
    return SimpleNamespace(limit_bytes=limit, min_free_bytes=floor, high_watermark=high, low_watermark=low)


# ── the rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("held, free, cfg, expected", [
    (50 * KB, 10**9, dict(), 0),                                       # nowhere near anything
    (95 * KB, 10**9, dict(), int(95 * KB - 70 * KB)),                  # over the HIGH watermark: down to LOW
    (90 * KB, 10**9, dict(), 0),                                       # exactly AT high is not over it
    (0, 6 * KB, dict(floor=8 * KB), int(8 * KB * 1.25) - 6 * KB),      # under the floor: back to floor + a quarter
    (0, 8 * KB, dict(floor=8 * KB), 0),                                # exactly AT the floor is not under it
    (95 * KB, 6 * KB, dict(floor=8 * KB), 25 * KB),                    # both: whichever needs more
    (95 * KB, 6 * KB, dict(floor=100 * KB), 100 * KB * 5 // 4 - 6 * KB),  # ... the floor can be the bigger
    (10**12, 0, dict(limit=0), 0),                                     # limit 0 = no limit; floor 0 = no floor
    (10**12, 0, dict(limit=None, floor=None), 0),                      # absent settings mean off
])
def test_capacity_pressure(held, free, cfg, expected):
    assert capacity_pressure(held, free, store(**cfg)) == expected


def test_relief_stops_short_of_flapping():
    """After freeing exactly what was asked, the node is clear of the trigger with room to spare."""
    s = store(floor=8 * KB)
    free = 6 * KB
    need = capacity_pressure(0, free, s)
    assert capacity_pressure(0, free + need, s) == 0
    assert free + need >= 8 * KB * (1 + FLOOR_MARGIN) - 1


# ── the observation ──────────────────────────────────────────────────────────

def test_a_real_disk_reports_what_an_ordinary_writer_can_add(tmp_path, monkeypatch):
    free = RealDisk(tmp_path).free_bytes()
    assert isinstance(free, int) and 0 < free <= 10**15
    # ext4 holds back a reserve for root: an ordinary writer (and the store) must be told the SMALLER number
    real = os.statvfs(tmp_path)
    monkeypatch.setattr(os, "statvfs", lambda p: os.statvfs_result(
        (real.f_bsize, 4096, 1000, 400, 150, real.f_files, real.f_ffree, real.f_favail, real.f_flag, real.f_namemax)))
    assert free_bytes(tmp_path) == 150 * 4096 and RealDisk(tmp_path).free_bytes() == 150 * 4096


def test_a_simulated_disk_shrinks_as_blobs_land_and_as_others_write(cluster_of):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    a.disk = SimDisk(a.root, capacity=20 * KB, other=4 * KB)
    assert a.disk.free_bytes() == 16 * KB
    a.edge_put([b"x" * 3000], "photos")
    assert a.disk.free_bytes() == 16 * KB - 3000
    a.disk.other = 40 * KB
    assert a.disk.free_bytes() == 0                                   # never negative


# ── check_capacity says why ──────────────────────────────────────────────────

def test_check_capacity_reports_both_readings_in_the_event(cluster_of):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    a.env_store.min_free_bytes = 8 * KB
    a.disk = SimDisk(a.root, capacity=20 * KB, other=10 * KB)
    a.edge_put([b"x" * 4096], "photos")                               # 6 KB free < the 8 KB floor
    a.run("check_capacity")
    (event,) = events_of(a, "space_pressure_detected")
    assert event["free_bytes"] == 20 * KB - 10 * KB - 4096
    assert event["used_bytes"] == 4096
    assert event["bytes_to_free"] == int(8 * KB * 1.25) - event["free_bytes"]
    assert any("free on the disk" in p.detail for p in a.progress if p.stage == "capacity")


def test_check_capacity_is_quiet_when_there_is_room(cluster_of):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    a.env_store.min_free_bytes = 4 * KB
    a.disk = SimDisk(a.root, capacity=100 * KB, other=0)
    a.edge_put([b"x" * 1000], "photos")
    a.run("check_capacity")
    assert events_of(a, "space_pressure_detected") == []


# ── uploads ──────────────────────────────────────────────────────────────────

def test_an_upload_is_refused_under_the_floor(cluster_of):
    a = cluster_of(a=ARCHIVE).nodes["a"]
    a.env_store.min_free_bytes = 8 * KB
    a.disk = SimDisk(a.root, capacity=20 * KB, other=14 * KB)         # 6 KB free
    with pytest.raises(OutOfSpace):
        a.edge_put([b"x" * 100], "photos")
    a.disk.other = 0
    assert a.edge_put([b"x" * 100], "photos")                         # room again: accepted


def test_the_blob_api_answers_507_when_the_disk_is_under_the_floor(tmp_path):
    root = tmp_path / "dev"
    assert cli(["--root", str(root), "init", "--node-id", "d", "--role", "archive", "--site", "lab",
                "--wants", "*", "--limit-bytes", "1GB", "--config", f"min_free_bytes={10**15}"]) == 0
    assert cli(["--root", str(root), "found"]) == 0
    device = Device.load(root)
    daemon = Daemon(device)
    client = TestClient(daemon.app, headers={"Authorization": f"Bearer {device['admin_token']}"})
    response = client.put("/admin/blob", params={"collection": "photos"}, content=b"hello")
    assert response.status_code == 507
    assert "floor" in response.json()["error"]
    daemon.node.close()
