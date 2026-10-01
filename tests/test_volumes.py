"""Reading what a path lives on from /proc and /sys — against a fake of each."""
from pathlib import Path

from conftest import make_disk, make_dm, mountinfo_line
from dizzy_store import volumes

SAMPLE = r"""22 1 259:2 / / rw,relatime shared:1 - ext4 /dev/mapper/ubuntu--vg-ubuntu--lv rw,errors=remount-ro
40 22 8:1 / /media/conrad/be4f14d9 rw,nosuid,nodev,relatime shared:99 - ext4 /dev/sda1 rw,errors=remount-ro
41 22 8:17 / /media/conrad/My\040Passport rw,nosuid shared:100 - exfat /dev/sdb1 rw,iocharset=utf8
50 22 0:44 / /run/user/1000 rw,nosuid,nodev,relatime shared:5 - tmpfs tmpfs rw,size=1M,mode=700
60 40 8:1 /sub /media/conrad/be4f14d9/bind rw,relatime - ext4 /dev/sda1 rw
"""


def test_mountinfo_parses_options_escapes_and_optional_fields():
    mounts = volumes.parse_mountinfo(SAMPLE)
    assert [m.fstype for m in mounts] == ["ext4", "ext4", "exfat", "tmpfs", "ext4"]
    wd = mounts[1]
    assert (wd.dev, wd.mountpoint, wd.source, wd.options) == ("8:1", "/media/conrad/be4f14d9", "/dev/sda1",
                                                              "rw,nosuid,nodev,relatime")
    assert mounts[2].mountpoint == "/media/conrad/My Passport"            # \040 is a space
    assert mounts[4].root == "/sub"                                       # a bind mount, with no optional fields
    assert volumes.parse_mountinfo("garbage\n\n") == []


def test_a_path_belongs_to_the_deepest_mount_containing_it(tmp_path):
    mounts = volumes.parse_mountinfo(SAMPLE)
    assert volumes.mount_for("/media/conrad/be4f14d9/dizzy-store/aa", mounts).dev == "8:1"
    assert volumes.mount_for("/media/conrad/be4f14d9/bind/x", mounts).root == "/sub"         # the later, deeper one
    assert volumes.mount_for("/media/conrad/be4f14d9-other", mounts).mountpoint == "/"        # not a prefix by name alone
    assert volumes.mount_for("/home/conrad", mounts).mountpoint == "/"
    assert volumes.mount_for("/", mounts).mountpoint == "/"


def test_a_usb_disk_is_read_through_its_partition(tmp_path):
    ids = make_disk(tmp_path, "sda", usb_speed=5000, rotational=1)
    mount = volumes.parse_mountinfo(mountinfo_line(40, ids["1"], "/media/x", "ext4", "/dev/sda1"))[0]
    p = volumes.placement_for(mount, tmp_path)
    assert p.layers == ["partition"] and not p.encrypted
    d = p.disk
    assert (d.name, d.transport, d.usb_mbps, d.rotational, d.removable) == ("sda", "usb", 5000, True, False)
    assert d.model == "WD WDC WD20SDRW" and d.size_bytes == 3906963456 * 512


def test_a_usb2_link_and_an_ssd_are_told_apart(tmp_path):
    ids = make_disk(tmp_path, "sdc", model="Flash", vendor="Gen", rotational=0, removable=1, usb_speed=480)
    mount = volumes.parse_mountinfo(mountinfo_line(41, ids["1"], "/media/f", "vfat", "/dev/sdc1"))[0]
    d = volumes.placement_for(mount, tmp_path).disk
    assert d.usb_mbps == 480 and d.rotational is False and d.removable is True


def test_luks_under_lvm_under_a_partition_is_found_to_be_encrypted(tmp_path):
    ids = make_disk(tmp_path, "nvme0n1", model="WD_BLACK SN850X", vendor="", rotational=0, bus="nvme",
                    parts=("3",), major=259)
    part = next((tmp_path / "devices/pci0000:00/0000:00:1d.0/nvme/nvme0/nvme0n1").glob("nvme0n13")).resolve()
    luks = make_dm(tmp_path, "dm-0", "252:0", "CRYPT-LUKS2-3efc7759-dm_crypt-0", part)
    make_dm(tmp_path, "dm-1", "252:1", "LVM-A5gRjsEeUx", luks)
    mount = volumes.parse_mountinfo(mountinfo_line(22, "252:1", "/", "ext4", "/dev/mapper/ubuntu--vg-ubuntu--lv"))[0]
    p = volumes.placement_for(mount, tmp_path)
    assert p.encrypted and p.lvm
    assert p.layers == ["lvm", "dm-crypt", "partition"]
    assert p.disk.name == "nvme0n1" and p.disk.transport == "nvme" and p.disk.rotational is False


def test_a_mount_with_no_block_device_has_no_disk(tmp_path):
    mount = volumes.parse_mountinfo(mountinfo_line(50, "0:44", "/run/user/1000", "tmpfs", "tmpfs"))[0]
    p = volumes.placement_for(mount, tmp_path)
    assert p.disks == [] and not p.encrypted
    assert volumes.placement_for(None).mount is None


def test_missing_sysfs_files_mean_unknown_not_a_crash(tmp_path):
    ids = make_disk(tmp_path, "sda")
    for f in list((tmp_path / "devices").rglob("rotational")) + list((tmp_path / "devices").rglob("speed")):
        f.unlink()
    mount = volumes.parse_mountinfo(mountinfo_line(40, ids["1"], "/media/x", "ext4", "/dev/sda1"))[0]
    d = volumes.placement_for(mount, tmp_path).disk
    assert d.rotational is None and d.usb_mbps is None


def test_same_filesystem(tmp_path):
    (tmp_path / "a").mkdir()
    assert volumes.same_filesystem(tmp_path, tmp_path / "a")
    assert not volumes.same_filesystem(tmp_path, tmp_path / "nope")
