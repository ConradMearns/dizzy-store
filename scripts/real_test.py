#!/usr/bin/env python3
"""A small, real, two-device test: a hot "server" and an archive "laptop".

    scripts/real_test.py --mode local      # rehearsal: two real daemons on this machine
    scripts/real_test.py --mode remote     # the real run: the laptop here, the server over SSH

Everything is driven through the shipped CLI (init / found / join / run / put /
get / status / cmd / query), over real sockets. In remote mode the laptop dials an
SSH tunnel to the server (-L to reach it, -R so it can reach us); nothing is
exposed publicly. The server side lives entirely under /opt/dizzy-store-test
(deployed and removed by server_ctl.sh) — the logger's data and services are never
touched. Run it from anywhere; it finds the repo from its own location.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STORE = Path(os.environ.get("STORE_PROJECT", str(REPO / "store")))
SERVER_IP = os.environ.get("SERVER_IP", "")       # --mode remote only: the address of the machine to run the second device on
REMOTE = "/opt/dizzy-store-test"
SERVER_PORT, LAPTOP_PORT = 7702, 7701
TOKEN = "t-" + hashlib.sha256(os.urandom(16)).hexdigest()[:32]
MB = 1024 * 1024

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, label))
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"   [{detail}]" if detail and not ok else ""))
    return ok


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while piece := f.read(1 << 20):
            h.update(piece)
    return h.hexdigest()


def wait_for(label: str, fn, timeout: float = 90.0, every: float = 1.5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = fn()
            if last:
                return last
        except Exception as exc:                  # keep polling through transient errors
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(every)
    print(f"     (timed out waiting for: {label}; last = {last!r})")
    return None


class Device:
    """One device, local or remote, driven through the CLI."""

    def __init__(self, name, role, site, port, root, remote: bool):
        self.name, self.role, self.site, self.port = name, role, site, port
        self.root, self.remote = root, remote
        self.proc: subprocess.Popen | None = None

    # command prefix -----------------------------------------------------------
    def _argv(self, *args) -> list[str]:
        py = ["python", "-m", "dizzy_store", "--root", str(self.root), *args]
        if self.remote:
            inner = (f"cd {REMOTE} && SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 UV_CACHE_DIR={REMOTE}/.uvcache "
                     f"PYTHONPATH={REMOTE}/store/src "
                     f"/root/.local/bin/uv run --frozen --no-dev --project store " + " ".join(map(_q, py)))
            return ["ssh", "-o", "ConnectTimeout=15", f"root@{SERVER_IP}", inner]
        return ["uv", "run", "--project", str(STORE), *py]

    def _env(self):
        env = dict(os.environ)
        if not self.remote:
            env["PYTHONPATH"] = str(STORE / "src")
        return env

    def cli(self, *args, check_rc=True, timeout=180) -> str:
        r = subprocess.run(self._argv(*args), capture_output=True, text=True,
                           env=self._env(), timeout=timeout)
        if check_rc and r.returncode != 0:
            raise RuntimeError(f"{self.name}: {' '.join(args)} -> rc {r.returncode}\n{r.stdout}\n{r.stderr}")
        return r.stdout

    def get_bytes(self, blob_hash: str) -> bytes:
        """`get` to stdout — binary-safe, so it works for a remote device too
        (an `-o PATH` would name a path on THAT machine)."""
        r = subprocess.run(self._argv("get", blob_hash), capture_output=True,
                           env=self._env(), timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"{self.name}: get {blob_hash[:12]} -> rc {r.returncode}\n{r.stderr.decode()}")
        return r.stdout

    def js(self, *args):
        return json.loads(self.cli(*args))

    def query(self, name, **kv):
        return self.js("query", name, *[f"{k}={json.dumps(v)}" for k, v in kv.items()])

    def status(self):
        return self.js("status")

    # lifecycle ----------------------------------------------------------------
    def start_daemon(self, logfile: Path):
        if self.remote:
            subprocess.run(["ssh", f"root@{SERVER_IP}", "systemctl restart dizzy-store-test"], check=True)
        else:
            self.proc = subprocess.Popen(self._argv("run"), stdout=open(logfile, "ab"),
                                         stderr=subprocess.STDOUT, env=self._env())
        wait_for(f"{self.name} daemon up", lambda: self.status().get("node_id") == self.name, 60)

    def stop_daemon(self):
        if self.remote:
            subprocess.run(["ssh", f"root@{SERVER_IP}", "systemctl stop dizzy-store-test"], check=False)
        elif self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def _q(s: str) -> str:
    import shlex
    return shlex.quote(s)


def blob_file(root: Path, blob_hash: str) -> Path:
    """Where a device keeps a blob: <root>/<aa>/<bb>/<sha256>."""
    return root / blob_hash[:2] / blob_hash[2:4] / blob_hash


def holders(dev: "Device", blob_hash: str) -> set[str]:
    """Which devices does `dev`'s log say hold this blob right now?"""
    r = dev.query("get_blob_replicas", blob_hash=blob_hash)
    return {n for n, st in zip(r["node_ids"], r["states"]) if st == "present"}


class Tunnel:
    """The laptop's dial-out: reach the server's port, and let the server reach ours."""

    def __init__(self):
        self.proc = None

    def up(self):
        self.proc = subprocess.Popen(
            ["ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=5",
             "-o", "ServerAliveCountMax=2", "-L", f"{SERVER_PORT}:127.0.0.1:{SERVER_PORT}",
             "-R", f"{LAPTOP_PORT}:127.0.0.1:{LAPTOP_PORT}", f"root@{SERVER_IP}"])
        time.sleep(2.5)
        assert self.proc.poll() is None, "ssh tunnel failed to start"

    def down(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        self.proc = None


CTL = str(Path(__file__).resolve().parent / "server_ctl.sh")


def ctl(command: str, check_rc: bool = True) -> None:
    subprocess.run(["bash", CTL, command], check=check_rc, env={**os.environ, "SERVER_IP": SERVER_IP})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["local", "remote"], default="local")
    ap.add_argument("--keep", action="store_true", help="leave everything in place afterwards")
    ap.add_argument("--no-deploy", action="store_true", help="remote: the server side is already deployed")
    args = ap.parse_args()
    remote = args.mode == "remote"
    if remote and not SERVER_IP:
        ap.error("--mode remote needs SERVER_IP=<address of the remote machine> in the environment (ssh as root)")

    work = Path(tempfile.mkdtemp(prefix="store-real-"))
    logs = work / "logs"
    logs.mkdir()
    srv_root = Path(f"{REMOTE}/data") if remote else work / "server"
    lap_root = work / "laptop"
    server = Device("server", "hot", "hetzner", SERVER_PORT, srv_root, remote)
    laptop = Device("laptop", "archive", "home", LAPTOP_PORT, lap_root, False)
    tunnel = Tunnel() if remote else None

    # deterministic test data (real photos are noise to a CAS anyway)
    rng = random.Random(20260930)
    files = {name: rng.randbytes(size) for name, size in
             [("photo-1.jpg", 2 * MB), ("photo-2.jpg", 2 * MB), ("photo-3.jpg", 2 * MB),
              ("movie.mp4", 30 * MB), ("late-photo.jpg", 1 * MB), ("rot.jpg", 1 * MB)]}
    src = work / "src"
    src.mkdir()
    digests = {}
    for name, data in files.items():
        (src / name).write_bytes(data)
        digests[name] = hashlib.sha256(data).hexdigest()

    try:
        print(f"== setup ({args.mode}); logs in {logs}")
        if remote:
            ctl("preflight")
            if not args.no_deploy:
                ctl("deploy")
        common = ["--peer-token", TOKEN, "--interval", "sync_s=4", "--interval", "sweep_s=8",
                  "--interval", "capacity_s=5", "--interval", "access_s=5", "--interval", "scrub_s=600",
                  "--config", "live_window_s=600", "--config", "high_watermark=0.9",
                  "--config", "chunk_threshold_bytes=16MB", "--config", "chunk_size=8MB"]
        server.cli("init", "--node-id", "server", "--role", "hot", "--site", "hetzner",
                   "--listen", f"127.0.0.1:{SERVER_PORT}", "--endpoint", f"http://127.0.0.1:{SERVER_PORT}",
                   "--limit-bytes", "20MB", "--config", "low_watermark=0.5", *common)
        laptop.cli("init", "--node-id", "laptop", "--role", "archive", "--site", "home", "--wants", "*",
                   "--listen", f"127.0.0.1:{LAPTOP_PORT}", "--endpoint", f"http://127.0.0.1:{LAPTOP_PORT}",
                   "--limit-bytes", "1GB", "--config", "low_watermark=0.5", *common)
        server.cli("found")
        if tunnel:
            tunnel.up()
        server.start_daemon(logs / "server.log")
        laptop.cli("join", "--url", f"http://127.0.0.1:{SERVER_PORT}")
        laptop.start_daemon(logs / "laptop.log")

        print("== 1. the devices find each other")
        ok = wait_for("both devices list the other as a peer", lambda:
                      [p["node_id"] for p in server.status()["peers"]] == ["laptop"]
                      and [p["node_id"] for p in laptop.status()["peers"]] == ["server"], 90)
        check(bool(ok), "server and laptop each know the other (cards replicated over the tunnel)")
        cl = (server.status()["cluster_id"], laptop.status()["cluster_id"])
        check(cl[0] is not None and cl[0] == cl[1], "they share one cluster id", str(cl))

        print("== 2. photos stored on the server reach the laptop, byte for byte")
        incoming = f"{REMOTE}/incoming" if remote else str(src)
        if remote:
            subprocess.run(["ssh", f"root@{SERVER_IP}", f"mkdir -p {incoming}"], check=True)
            subprocess.run(["scp", "-q", *[str(src / n) for n in files], f"root@{SERVER_IP}:{incoming}/"], check=True)
        for n in ("photo-1.jpg", "photo-2.jpg", "photo-3.jpg"):
            out = server.cli("put", f"{incoming}/{n}", "--collection", "photos")
            check(out.split()[0] == digests[n], f"server put {n} -> the sha256 it should be")
        ok = wait_for("laptop holds 3 blobs", lambda: laptop.status()["held_count"] == 3, 90)
        check(bool(ok), "the laptop replicated all three")
        for n in ("photo-1.jpg", "photo-2.jpg", "photo-3.jpg"):
            out = work / f"laptop-{n}"
            laptop.cli("get", digests[n], "-o", str(out))
            check(out.exists() and sha(out) == digests[n], f"laptop copy of {n} matches the original")
        check(laptop.query("get_at_risk_blobs")["blob_hashes"] == [], "nothing is at risk")

        print("== 3. a large file (30 MB) moves as verified chunks")
        server.cli("put", f"{incoming}/movie.mp4", "--collection", "video")
        blob = server.query("get_blob", blob_hash=digests["movie.mp4"])
        check(blob.get("chunk_size") == 8 * MB and len(blob.get("chunk_hashes") or []) == 4,
              "the movie was registered with a 4-chunk recipe", str(blob.get("chunk_size")))
        ok = wait_for("laptop holds the movie", lambda: laptop.status()["held_count"] == 4, 180)
        check(bool(ok), "the laptop assembled the chunked file")
        out = work / "laptop-movie.mp4"
        laptop.cli("get", digests["movie.mp4"], "-o", str(out))
        check(out.exists() and sha(out) == digests["movie.mp4"], "the assembled movie matches the original")

        print("== 4. space pressure: the hot server evicts what the laptop provably holds")
        ok = wait_for("server drops below its low watermark", lambda:
                      server.status()["held_bytes"] <= 10 * MB, 120)
        st = server.status()
        check(bool(ok), "the server shrank under its limit", f"held {st['held_bytes']}")
        check(laptop.status()["held_count"] == 4, "the laptop still holds every blob")
        check(laptop.query("get_at_risk_blobs")["blob_hashes"] == [], "still nothing at risk")

        print("== 5. read-through: ask the server for something it evicted")
        evicted = [n for n in ("photo-1.jpg", "photo-2.jpg", "photo-3.jpg", "movie.mp4")
                   if "server" not in holders(server, digests[n])]
        check(bool(evicted), "at least one blob is no longer held by the server", f"evicted={evicted}")
        target = evicted[0]
        served = server.get_bytes(digests[target])
        check(hashlib.sha256(served).hexdigest() == digests[target],
              f"server served {target} by fetching it back from the laptop")
        check("server" in holders(server, digests[target]),
              f"and the server holds {target} again afterwards")

        print("== 6. an outage: the link drops, nothing unsafe happens, then it heals")
        if remote:
            tunnel.down()
        else:
            laptop.stop_daemon()
        link = wait_for("server records the link down", lambda:
                        server.query("get_peer_link", node_id="server", peer_id="laptop").get("healthy") is False, 90)
        check(bool(link), "the server noticed the laptop is unreachable (one peer_link_changed fact)")
        held_now = [n for n in ("photo-1.jpg", "photo-2.jpg", "photo-3.jpg", "movie.mp4")
                    if "server" in holders(server, digests[n])]
        if held_now:
            h = digests[held_now[0]]
            server.cli("cmd", "evict_blob", f"blob_hash={json.dumps(h)}", 'reason="pressure"', check_rc=False)
            check("server" in holders(server, h),
                  f"with the laptop unreachable the server refused to evict {held_now[0]}")
        else:
            print("     (the server held nothing at this point, so there was nothing to refuse)")
        server.cli("put", f"{incoming}/late-photo.jpg", "--collection", "photos")
        if remote:
            tunnel.up()
        else:
            laptop.start_daemon(logs / "laptop.log")
        ok = wait_for("laptop catches up on the photo stored during the outage", lambda:
                      laptop.status()["held_count"] == 5, 120)
        check(bool(ok), "after the link healed the laptop caught up")
        out = work / "laptop-late.jpg"
        laptop.cli("get", digests["late-photo.jpg"], "-o", str(out))
        check(out.exists() and sha(out) == digests["late-photo.jpg"], "and the late photo is intact")
        link = wait_for("server records the link up", lambda:
                        server.query("get_peer_link", node_id="server", peer_id="laptop").get("healthy") is True, 60)
        check(bool(link), "the link is healthy again")

        print("== 7. bit rot: a rotted copy never anchors an eviction, and is found and repaired")
        server.cli("put", f"{incoming}/rot.jpg", "--collection", "photos")
        h = digests["rot.jpg"]
        ok = wait_for("laptop holds the rot-test photo", lambda: "laptop" in holders(laptop, h), 90)
        check(bool(ok), "the laptop replicated the photo that is about to rot")
        ok = wait_for("server's log shows the laptop's copy", lambda: "laptop" in holders(server, h), 60)
        check(bool(ok), "and the server has heard of it")
        path = blob_file(lap_root, h)
        raw = bytearray(path.read_bytes())
        raw[0] ^= 0xFF
        path.write_bytes(bytes(raw))                          # same size, one byte flipped
        server.cli("cmd", "evict_blob", f"blob_hash={json.dumps(h)}", 'reason="pressure"', check_rc=False)
        check("server" in holders(server, h) and hashlib.sha256(server.get_bytes(h)).hexdigest() == h,
              "the server refused to evict: the laptop's log still said it held the photo, its bytes did not")
        check(any(r.startswith("evict_refused") and h[:12] in r and "proven live" in r
                  for r in server.status()["recent"]),
              "and said why: no site could prove it live")
        laptop.cli("cmd", "scrub_blobs", "max_bytes=1073741824")
        check("laptop" not in holders(laptop, h) and not path.exists(),
              "the laptop's scrub found the rot and moved the bad copy aside")
        laptop.cli("sweep")                                   # repair is the paced sweep's job
        ok = wait_for("laptop repairs its copy from the server", lambda:
                      path.exists() and sha(path) == h, 90)
        check(bool(ok), "the laptop repaired it from the server (verified against its address)")
        ok = wait_for("server's log shows the repaired copy", lambda: "laptop" in holders(server, h), 60)
        check(bool(ok), "and the repair reached the server's log")
        server.cli("cmd", "evict_blob", f"blob_hash={json.dumps(h)}", 'reason="pressure"', check_rc=False)
        check("server" not in holders(server, h), "now the server may leave: the laptop's copy is proven good")

        print("== 8. final state")
        check(laptop.query("get_at_risk_blobs")["blob_hashes"] == [], "nothing at risk at the end")
        for n, d in digests.items():
            out = work / f"final-{n}"
            laptop.cli("get", d, "-o", str(out))
            if not (out.exists() and sha(out) == d):
                check(False, f"final: laptop copy of {n} is intact")
                break
        else:
            check(True, "every file is intact on the laptop")
        print("   server:", json.dumps({k: server.status()[k] for k in ("held_count", "held_bytes", "events")}))
        print("   laptop:", json.dumps({k: laptop.status()[k] for k in ("held_count", "held_bytes", "events")}))
    except Exception:
        import traceback
        traceback.print_exc()
        check(False, "the run completed without an unexpected error")
    finally:
        print("== teardown" + (" (skipped: --keep)" if args.keep else ""))
        if not args.keep:
            laptop.stop_daemon()
            server.stop_daemon()
            if tunnel:
                tunnel.down()
        for name in ("server", "laptop"):
            lg = logs / f"{name}.log"
            if lg.exists() and any(not ok for ok, _ in results):
                print(f"-- {name}.log (tail)")
                print("\n".join(lg.read_text().splitlines()[-25:]))
        if remote and not args.keep:
            ctl("teardown", check_rc=False)
            ctl("verify-clean", check_rc=False)
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for label in failed:
        print("  FAILED:", label)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
