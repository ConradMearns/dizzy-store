"""The timing rules of `run --until-idle`, pinned exactly.

`_watch_idle` decides when a drive is done. It reads four things from the daemon — whether it is listening,
how many passes it has made, which peers answer / are in step, and what is still wanted — so here the daemon is a
SCRIPT: those four are functions of time. No sockets, nothing but the rule itself to wait for. (Real daemons on real
sockets are in test_idle.py.)

The watcher looks once a second, so assertions leave about a second of slack.
"""
import threading
import time
from types import SimpleNamespace

import pytest

from dizzy_store import daemon as daemon_module
from dizzy_store.daemon import Daemon, IdlePolicy, _watch_idle
from dizzy_store.device import Device
from dizzy_store.exitcodes import EX_TEMPFAIL
from storeutil import PeerUnreachable


class Scripted:
    def __init__(self, *, reached_at=0.0, in_step_at=0.0, wanted=lambda t: 0, backing_off=lambda t: 0,
                 events=lambda t: 1, passes=3, listening=True):
        self.t0 = time.monotonic()
        self.reached_at, self.in_step_at = reached_at, in_step_at
        self.wanted, self.backing_off, self.events = wanted, backing_off, events
        self.passes = passes
        self.listening = threading.Event()
        if listening:
            self.listening.set()
        self.stop = threading.Event()
        self.idle_result = None
        self.reached: set[str] = set()
        self.in_step: set[str] = set()

    def now(self) -> float:
        return time.monotonic() - self.t0

    def compare_with_peers(self) -> None:
        t = self.now()
        self.reached = {"server"} if self.reached_at is not None and t >= self.reached_at else set()
        self.in_step = {"server"} if self.in_step_at is not None and t >= self.in_step_at else set()

    def activity(self):
        t = self.now()
        return (self.events(t), 10, self.wanted(t), self.backing_off(t))

    def peer_ids(self):
        return ["server"]

    def summary(self) -> str:
        return "scripted"


def watch(daemon: Scripted, **policy):
    server = SimpleNamespace(should_exit=False)
    said: list[str] = []
    settings = dict(settle_s=1.0, grace_s=2.0, stall_s=2.0, report_s=60.0, max_s=30.0) | policy
    started = time.monotonic()
    guard = threading.Timer(settings["max_s"] + 6.0, daemon.stop.set)     # a broken rule fails the test, never hangs it
    guard.start()
    try:
        _watch_idle(daemon, server, IdlePolicy(**settings), said.append)
    finally:
        guard.cancel()
    return daemon.idle_result, time.monotonic() - started, server, said


def test_a_quiet_device_with_a_peer_in_step_is_done_as_soon_as_the_quiet_has_lasted():
    (code, message), took, server, _ = watch(Scripted())
    assert code == 0 and message == "up to date — scripted"
    assert server.should_exit and 1.0 <= took < 4.0                  # a look, then a settle's worth of nothing


def test_nothing_is_judged_before_the_first_full_pass():
    (code, message), took, _, _ = watch(Scripted(passes=0), max_s=2.5)
    assert code == EX_TEMPFAIL and message.startswith("gave up")      # never "up to date"


def test_nothing_is_judged_before_the_listener_is_up():
    (code, message), _, _, _ = watch(Scripted(listening=False), max_s=2.5)
    assert code == EX_TEMPFAIL and message.startswith("gave up")


def test_it_waits_for_the_log_to_stop_changing():
    (code, _), took, _, _ = watch(Scripted(events=lambda t: int(t) if t < 3 else 3))
    assert code == 0 and took >= 3.5                                  # changes until ~3s, then a settle's quiet


def test_being_in_step_is_required_and_waited_for():
    (code, _), took, _, _ = watch(Scripted(in_step_at=2.6), stall_s=20.0)
    assert code == 0 and took >= 3.0                                  # not at the first quiet moment


def test_blobs_still_wanted_keep_it_running_until_they_are_fetched():
    daemon = Scripted(wanted=lambda t: 3 if t < 3 else 0)
    (code, message), took, _, said = watch(daemon, report_s=1.0)
    assert code == 0 and message.startswith("up to date") and took >= 3.0
    assert any("3 still wanted" in line for line in said)             # and it says how it is getting on


def test_blobs_that_are_all_backing_off_are_a_retry_later_not_a_wait_forever():
    (code, message), took, _, _ = watch(Scripted(wanted=lambda t: 2, backing_off=lambda t: 2))
    assert code == EX_TEMPFAIL and "2 wanted blobs could not be fetched" in message and took < 5.0


def test_some_blobs_backing_off_while_others_are_still_coming_is_not_yet_a_verdict():
    (code, message), _, _, _ = watch(Scripted(wanted=lambda t: 2, backing_off=lambda t: 1), max_s=3.5)
    assert code == EX_TEMPFAIL and message.startswith("gave up")


def test_a_peer_that_answers_but_never_comes_in_step_is_reported_after_the_stall_time():
    (code, message), took, _, _ = watch(Scripted(in_step_at=None), stall_s=2.5)
    assert code == EX_TEMPFAIL and "cannot get in step" in message and "reach back" in message
    assert 3.0 <= took < 7.0                                          # not at once, and not never


def test_a_stall_verdict_needs_a_peer_to_have_answered_at_all():
    (code, message), _, _, _ = watch(Scripted(reached_at=None, in_step_at=None), grace_s=2.0)
    assert code == EX_TEMPFAIL and message.startswith("reached no peer")


def test_the_grace_period_is_waited_out_before_giving_up_on_the_network():
    (code, message), took, _, _ = watch(Scripted(reached_at=2.3, in_step_at=2.3), grace_s=5.0)
    assert code == 0 and took >= 3.0                                  # the network came up late; it was waited for


def test_no_peer_at_all_within_the_grace_period_is_a_retry_later():
    (code, message), took, _, _ = watch(Scripted(reached_at=None, in_step_at=None), grace_s=2.0)
    assert code == EX_TEMPFAIL and "reached no peer" in message and "server" in message
    assert 2.0 <= took < 6.0


def test_the_overall_ceiling_applies_even_while_progress_is_being_made():
    (code, message), took, _, _ = watch(Scripted(events=lambda t: int(t * 20)), max_s=3.0)
    assert code == EX_TEMPFAIL and message == "gave up after 3s — scripted"
    assert 3.0 <= took < 4.5


def test_a_stop_from_elsewhere_ends_the_watch_without_a_verdict():
    daemon = Scripted(in_step_at=None)
    threading.Timer(0.8, daemon.stop.set).start()
    _, took, _, _ = watch(daemon, stall_s=30.0)
    assert daemon.idle_result is None and took < 3.0


def test_a_surprise_while_looking_does_not_end_the_watch(caplog):
    class Flaky(Scripted):
        looks = 0

        def compare_with_peers(self):
            Flaky.looks += 1
            if Flaky.looks == 1:
                raise RuntimeError("a peer sent nonsense")
            super().compare_with_peers()

    (code, _), took, _, _ = watch(Flaky())
    assert code == 0 and Flaky.looks >= 2 and "could not look at the device" in caplog.text


# ── what "in step" means: the peer's digest of the log against ours ──────────

@pytest.fixture
def idle_device(tmp_path):
    from dizzy_store.cli import main as cli
    root = tmp_path / "drive"
    assert cli(["--root", str(root), "init", "--node-id", "drive", "--role", "archive", "--site", "home",
                "--wants", "*", "--limit-bytes", "1GB"]) == 0
    assert cli(["--root", str(root), "found"]) == 0
    daemon = Daemon(Device.load(root))
    daemon.peer_ids = lambda: ["server"]                              # one peer, whose answers the test scripts
    yield daemon
    daemon.node.close()


def test_a_peer_counts_as_reached_and_in_step_only_while_it_answers_and_holds_exactly_our_events(idle_device, monkeypatch):
    daemon = idle_device
    ours = daemon.node.surface.buckets()
    script = iter(["same", "gone", "different", "same"])

    class Peer:
        def __init__(self, peers, peer_id):
            assert peer_id == "server"

        def buckets(self):
            what = next(script)
            if what == "gone":
                raise PeerUnreachable("server unreachable")
            return dict(ours) if what == "same" else {**ours, "ff": "someone-elses-event"}

    monkeypatch.setattr(daemon_module, "RemoteSurface", Peer)
    seen = []
    for _ in range(4):
        daemon.compare_with_peers()
        seen.append((sorted(daemon.reached), sorted(daemon.in_step)))
    assert seen == [(["server"], ["server"]),            # answers, same events: in step
                    ([], []),                            # went away: neither
                    (["server"], []),                    # back, but holds something we lack
                    (["server"], ["server"])]            # and caught up again


def test_talking_to_a_peer_happens_under_the_daemon_lock(idle_device, monkeypatch):
    """The peers client reads the node's read models (a SQLAlchemy session — not thread-safe) to find a peer's
    address. Run beside the tick it corrupted memory and crashed the interpreter; so it must hold the lock the tick holds."""
    daemon = idle_device
    seen = []

    class Peer:
        def __init__(self, peers, peer_id):
            pass

        def buckets(self):
            free = []
            probe = threading.Thread(target=lambda: free.append(daemon.lock.acquire(blocking=False)))
            probe.start()
            probe.join()
            if free[0]:
                daemon.lock.release()
            seen.append(not free[0])                      # True: another thread could NOT take the lock
            return daemon.node.surface.buckets()

    monkeypatch.setattr(daemon_module, "RemoteSurface", Peer)
    daemon.compare_with_peers()
    assert seen == [True]


def test_the_summary_names_who_is_in_step_who_answers_and_who_does_not(idle_device):
    daemon = idle_device
    daemon.peer_ids = lambda: ["a", "b", "c"]
    daemon.reached, daemon.in_step = {"a", "b"}, {"a"}
    text = daemon.summary()
    assert "in step with a" in text and "answering but not in step b" in text and "not answering c" in text
    assert "0 blobs held" in text
