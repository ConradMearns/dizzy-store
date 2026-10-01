#!/usr/bin/env python3
"""A real test of the systemd user unit: your user manager, a throwaway store, nothing of yours touched.

    store/scripts/systemd_test.py            # install the unit (if needed), run the checks, clean up
    store/scripts/systemd_test.py --uninstall   # ... and remove the unit template afterwards

It installs the template unit with `dizzy-store service install` (idempotent — that is the real
deliverable), points the user manager at a THROWAWAY config through its environment
(`systemctl --user set-environment DIZZY_STORE_CONFIG=…`, removed at the end), and runs two instances:

  systest-ok    start returns only when the listener really answers (Type=notify); `reload` applies a
                changed limit to the running daemon; a bad config is refused and the old one kept;
                `stop` is a clean success (exit 0, nothing restarts it)
  systest-gone  a device whose root is not there exits 78 and is NOT restarted — the whole point of
                RestartPreventExitStatus=78, so an unmounted drive does not spin

Needs `dizzy-store` on PATH (`uv tool install --editable ./store`) and a running user manager.
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((bool(ok), label))
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""), flush=True)
    return bool(ok)


def sc(*args: str, check_rc: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, check=check_rc)


def prop(unit: str, *names: str) -> dict[str, str]:
    out = sc("show", unit, "-p", ",".join(names)).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def tool(*args: str, cfg: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["dizzy-store", "--config", str(cfg), *args], capture_output=True, text=True)


def wait_for(predicate, seconds: float, interval: float = 0.2) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uninstall", action="store_true", help="remove the unit template afterwards")
    args = ap.parse_args()
    if not shutil.which("dizzy-store") or not shutil.which("systemctl"):
        print("needs `dizzy-store` on PATH (uv tool install --editable ./store) and systemd")
        return 2
    work = Path(tempfile.mkdtemp(prefix="store-systest-"))
    cfg = work / "config.yaml"
    ok_port, gone_port = free_port(), free_port()
    ok_root = work / "ok"

    def write_config(limit: str, extra: dict | None = None) -> None:
        doc = {"devices": {
            "systest-ok": {"root": str(ok_root), "listen": f"127.0.0.1:{ok_port}", "limit": limit, **(extra or {})},
            "systest-gone": {"root": str(work / "unmounted" / "dizzy-store"), "listen": f"127.0.0.1:{gone_port}",
                             "limit": "1GB"}}}
        cfg.write_text(yaml.safe_dump(doc))

    try:
        print("== setup")
        unit = subprocess.run(["dizzy-store", "service", "install"], capture_output=True, text=True)
        check(unit.returncode == 0, "the unit template installs", unit.stderr)
        write_config("1GB")
        for step in (["-d", "systest-ok", "init", "--role", "archive", "--site", "lab", "--wants", "*"],
                     ["-d", "systest-ok", "found"]):
            r = tool(*step, cfg=cfg)
            if r.returncode != 0:
                check(False, f"setup {' '.join(step)}", r.stderr)
                return 1
        sc("set-environment", f"DIZZY_STORE_CONFIG={cfg}")

        print("== 1. systest-ok: readiness, reload, clean stop")
        started = time.time()
        r = sc("start", "dizzy-store@systest-ok.service")
        took = time.time() - started
        check(r.returncode == 0, "`start` returns success", r.stderr)
        p = prop("dizzy-store@systest-ok.service", "ActiveState", "SubState", "Type", "NotifyAccess")
        check(p.get("ActiveState") == "active" and p.get("Type") == "notify",
              "it is active and a notify service", str(p))
        status = tool("-d", "systest-ok", "status", cfg=cfg)
        check(status.returncode == 0 and json.loads(status.stdout or "{}").get("node_id") == "systest-ok",
              f"the moment `start` returned, the daemon answered (start took {took:.1f}s)", status.stderr)

        write_config("7GB")
        reload = sc("reload", "dizzy-store@systest-ok.service")
        check(reload.returncode == 0, "`reload` is accepted", reload.stderr)
        check(wait_for(lambda: json.loads(tool("-d", "systest-ok", "status", cfg=cfg).stdout or "{}")
                       .get("limit_bytes") == 7 * 1024 ** 3, 15),
              "the reloaded limit (7GB) is in force in the running daemon")

        cfg.write_text("devices: [this is not valid")
        sc("reload", "dizzy-store@systest-ok.service")
        time.sleep(2.5)
        write_config("7GB")                          # a client needs a readable file to find the daemon
        status = json.loads(tool("-d", "systest-ok", "status", cfg=cfg).stdout or "{}")
        check(status.get("limit_bytes") == 7 * 1024 ** 3, "a broken config was refused: the running one was kept")
        logs = subprocess.run(["journalctl", "--user", "-u", "dizzy-store@systest-ok", "--no-pager", "-o", "cat",
                               "-n", "40"], capture_output=True, text=True).stdout
        check("reload refused" in logs, "…and the refusal is in the journal", logs[-300:])

        sc("stop", "dizzy-store@systest-ok.service")
        p = prop("dizzy-store@systest-ok.service", "ActiveState", "Result", "ExecMainStatus", "NRestarts")
        check(p.get("ActiveState") == "inactive" and p.get("Result") == "success" and p.get("ExecMainStatus") == "0",
              "`stop` is a clean success (exit 0)", str(p))
        time.sleep(7)
        check(prop("dizzy-store@systest-ok.service", "ActiveState")["ActiveState"] == "inactive",
              "and nothing restarts it")

        print("== 2. systest-gone: an unmounted drive")
        r = sc("start", "dizzy-store@systest-gone.service")
        check(r.returncode != 0, "`start` fails, because the store is not there", r.stdout + r.stderr)
        p = prop("dizzy-store@systest-gone.service", "ActiveState", "Result", "ExecMainStatus", "NRestarts")
        check(p.get("ExecMainStatus") == "78", "it exited 78 (a configuration problem)", str(p))
        time.sleep(8)                                # RestartSec is 5: give a restart every chance to happen
        p = prop("dizzy-store@systest-gone.service", "ActiveState", "NRestarts")
        check(p.get("NRestarts") == "0" and p.get("ActiveState") == "failed",
              "…and it was NOT restarted (RestartPreventExitStatus=78)", str(p))
        logs = subprocess.run(["journalctl", "--user", "-u", "dizzy-store@systest-gone", "--no-pager", "-o", "cat",
                               "-n", "10"], capture_output=True, text=True).stdout
        check("is not a store device" in logs, "…with the reason in the journal", logs[-300:])
    finally:
        print("== cleanup")
        for name in ("systest-ok", "systest-gone"):
            sc("stop", f"dizzy-store@{name}.service")
            sc("reset-failed", f"dizzy-store@{name}.service")
        sc("unset-environment", "DIZZY_STORE_CONFIG")
        if args.uninstall:
            subprocess.run(["dizzy-store", "service", "uninstall"], capture_output=True)
        shutil.rmtree(work, ignore_errors=True)
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for label in failed:
        print("  FAILED:", label)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
