"""A device's state travels with its drive; this machine's settings overlay it and are never written back."""
import json

from dizzy_store.config import DeviceSettings
from dizzy_store.device import Device, device_file


def make(tmp_path, settings=None):
    Device.init(tmp_path / "dev", node_id="d", role="archive", site="home", wants=["*"],
                listen="127.0.0.1:7700", endpoints=["http://old:7700"], seeds={"server": "http://learned:1"},
                config={"limit_bytes": 10**9, "high_watermark": 0.9})
    return Device.load(tmp_path / "dev", settings)


def test_machine_settings_overlay_the_state_in_force(tmp_path):
    d = make(tmp_path, DeviceSettings(listen="127.0.0.1:7777", endpoints=["http://new:7777"],
                                      seeds={"nas": "http://nas:1"}, intervals={"sync_s": 3},
                                      limit="5GB", min_free="1GB"))
    assert d["listen"] == "127.0.0.1:7777" and d.host_port == ("127.0.0.1", 7777)
    assert d["endpoints"] == ["http://new:7777"] and d.card["endpoints"] == ["http://new:7777"]
    assert d["seeds"] == {"server": "http://learned:1", "nas": "http://nas:1"}      # learned + configured
    assert d["intervals"]["sync_s"] == 3 and d["intervals"]["sweep_s"] == 60         # overlaid, not replaced
    assert d["config"] == {"limit_bytes": 5 * 1024 ** 3, "high_watermark": 0.9, "min_free_bytes": 1024 ** 3}


def test_without_settings_the_drives_own_values_are_in_force(tmp_path):
    d = make(tmp_path)
    assert d["listen"] == "127.0.0.1:7700" and d["endpoints"] == ["http://old:7700"]
    assert d["config"]["limit_bytes"] == 10**9


def test_saving_never_bakes_a_machine_setting_into_the_drive(tmp_path, monkeypatch):
    monkeypatch.setenv("DIZZY_STORE_HOST", "marrus")
    d = make(tmp_path, DeviceSettings(listen="127.0.0.1:7777", endpoints=["http://new:7777"], limit="5GB",
                                      site="office", seeds={"nas": "http://nas:1"}, intervals={"sync_s": 3}))
    d.data["cluster_id"] = "c-1"                        # something that really is state
    d.save()
    on_drive = json.loads(device_file(tmp_path / "dev").read_text())
    assert on_drive["cluster_id"] == "c-1"
    # the drive's generic values are untouched; what `init` was told is filed under THIS computer's name
    assert on_drive["listen"] == "127.0.0.1:7700" and on_drive["endpoints"] == [] and on_drive["seeds"] == {}
    assert on_drive["hosts"] == {"marrus": {"listen": "127.0.0.1:7700", "endpoints": ["http://old:7700"],
                                            "seeds": {"server": "http://learned:1"}}}
    assert on_drive["config"]["limit_bytes"] == 10**9 and on_drive["intervals"]["sync_s"] == 30
    assert on_drive["site"] == "home"                   # the machine said "office"; the drive still says home
    assert "nas" not in json.dumps(on_drive) and "7777" not in json.dumps(on_drive)
    # the same drive "plugged into another computer" sees its own values again
    assert Device.load(tmp_path / "dev")["listen"] == "127.0.0.1:7700"


def test_a_drive_remembers_what_is_true_on_each_computer_and_nothing_leaks_between_them(tmp_path, monkeypatch):
    monkeypatch.setenv("DIZZY_STORE_HOST", "laptop")
    make(tmp_path)                                       # init: listen/endpoints/seeds said HERE (on `laptop`)
    here = Device.load(tmp_path / "dev")
    assert here["listen"] == "127.0.0.1:7700" and here["endpoints"] == ["http://old:7700"]
    assert here["seeds"] == {"server": "http://learned:1"}

    monkeypatch.setenv("DIZZY_STORE_HOST", "desktop")    # the drive moves to another computer
    there = Device.load(tmp_path / "dev")
    assert there["endpoints"] == [] and there["seeds"] == {}          # the laptop's tunnel addresses do not follow it
    there.remember_seed("nas", "http://nas.lan:7702")
    there.remember("listen", "127.0.0.1:7790")
    there.save()
    assert Device.load(tmp_path / "dev")["seeds"] == {"nas": "http://nas.lan:7702"}
    assert Device.load(tmp_path / "dev")["listen"] == "127.0.0.1:7790"       # what the drive remembers of THIS computer

    monkeypatch.setenv("DIZZY_STORE_HOST", "laptop")     # and back: exactly as it was left
    back = Device.load(tmp_path / "dev")
    assert back["seeds"] == {"server": "http://learned:1"} and back["listen"] == "127.0.0.1:7700"
    assert Device.load(tmp_path / "dev", DeviceSettings(listen="127.0.0.1:7791"))["listen"] == "127.0.0.1:7791"   # config still wins


def test_machine_config_still_beats_what_the_drive_remembers_of_this_machine(tmp_path, monkeypatch):
    monkeypatch.setenv("DIZZY_STORE_HOST", "laptop")
    make(tmp_path)
    d = Device.load(tmp_path / "dev", DeviceSettings(endpoints=["http://configured:1"], seeds={"server": "http://cfg:2"}))
    assert d["endpoints"] == ["http://configured:1"] and d["seeds"] == {"server": "http://cfg:2"}


def test_a_machine_says_where_it_is_and_the_drive_announces_that(tmp_path):
    drive = make(tmp_path)
    assert drive.card["site"] == "home"
    at_the_office = Device.load(tmp_path / "dev", DeviceSettings(site="office", location_note="in the bag"))
    assert at_the_office.card["site"] == "office" and at_the_office.card["location_note"] == "in the bag"
    assert at_the_office["site"] == "office"
    node = at_the_office.build_node()
    try:
        assert node.card["site"] == "office"
    finally:
        node.close()
    assert Device.load(tmp_path / "dev").card["site"] == "home"        # and the drive itself never changed


def test_the_small_blob_exemption_reaches_the_node_and_defaults_to_off(tmp_path):
    d = make(tmp_path, DeviceSettings(min_evict="1MB"))
    assert d["config"]["min_evict_bytes"] == 1024 ** 2
    node = d.build_node()
    try:
        assert node.env_store.min_evict_bytes == 1024 ** 2
    finally:
        node.close()
    plain = make(tmp_path / "plain").build_node()           # no setting anywhere: today's behaviour, unchanged
    try:
        assert plain.env_store.min_evict_bytes == 0
    finally:
        plain.close()


def test_the_node_is_built_from_what_is_in_force(tmp_path):
    d = make(tmp_path, DeviceSettings(limit="2GB", min_free="500MB", endpoints=["http://new:1"]))
    node = d.build_node()
    try:
        assert node.env_store.limit_bytes == 2 * 1024 ** 3 and node.env_store.min_free_bytes == 500 * 1024 ** 2
        assert node.card["endpoints"] == ["http://new:1"]
        assert node._create_root is False                # a real device never conjures its root
    finally:
        node.close()
