"""About the installed tool itself: what is running, where its source lives, how to update it.

The install is EDITABLE (`uv tool install --editable ./store`): `dizzy-store` on PATH runs the code
in the git checkout, so updating is a matter of getting new code into the checkout and restarting
whatever is running the old. `update` is that recipe in one command, so the steps people forget
(reinstall when the dependencies changed, restart the daemons) are not forgotten:

    dizzy-store update                 reinstall from the checkout, restart running devices
    dizzy-store update --pull          git pull --ff-only first (refuses over uncommitted changes)

What makes it SAFE: a start that finds the read models were built by different code or a different
schema rebuilds them from the log (fingerprint.py); the log itself only ever grows by additive
changes to events.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from . import _kit

Runner = Callable[..., "subprocess.CompletedProcess"]


def source_dir() -> Path:
    """The checkout's store/ directory — where the editable install points."""
    return _kit.STORE_ROOT


def _git(directory: Path, *args: str, runner: Runner = subprocess.run) -> Optional[str]:
    try:
        result = runner(["git", "-C", str(directory), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def repo_dir(runner: Runner = subprocess.run) -> Optional[Path]:
    top = _git(source_dir(), "rev-parse", "--show-toplevel", runner=runner)
    return Path(top) if top else None


def _commit(directory: Path) -> str:
    short = _git(directory, "rev-parse", "--short", "HEAD")
    if not short:
        return "(not a git checkout)"
    dirty = _git(directory, "status", "--porcelain", "--untracked-files=no")
    branch = _git(directory, "rev-parse", "--abbrev-ref", "HEAD") or "?"
    return f"{short} on {branch} ({'uncommitted changes' if dirty else 'clean'})"


def version_info() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version
    from .config import load_config
    from .fingerprint import readmodel_fingerprint
    try:
        package = version("dizzy-store")
    except PackageNotFoundError:
        package = "(not installed — running from the source tree)"
    info = {
        "dizzy-store": package,
        "source": str(source_dir()),
        "commit": _commit(source_dir()),
        "dizzy (ext)": _commit(_kit.REPO_ROOT / "ext" / "dizzy"),
        "python": f"{sys.version.split()[0]} at {sys.executable}",
        "read models": readmodel_fingerprint()[:16],
    }
    try:
        files = load_config().files
        info["config files"] = ", ".join(str(f) for f in files) or "(none found: `dizzy-store config`)"
    except Exception as exc:                        # a broken config must not hide the version
        info["config files"] = f"(unreadable: {exc})"
    return info


def _uv() -> str:
    found = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    if not Path(found).exists():
        raise RuntimeError("`uv` not found — it is what installs the tool (https://docs.astral.sh/uv/)")
    return found


def update(pull: bool = False, restart: bool = True, dry_run: bool = False,
           runner: Runner = subprocess.run, say: Callable[[str], None] = print) -> int:
    """Bring the installed tool up to date with its checkout. Returns an exit status."""
    plan: list[tuple[str, list[str], Optional[Path]]] = []
    repo = repo_dir(runner)
    if pull:
        if repo is None:
            say("error: --pull needs the tool to be installed from a git checkout")
            return 1
        if _git(repo, "status", "--porcelain", "--untracked-files=no", runner=runner):
            say(f"error: {repo} has uncommitted changes to tracked files — commit or stash them, "
                "or update without --pull")
            return 1
        plan.append(("pull the checkout", ["git", "-C", str(repo), "pull", "--ff-only"], None))
    try:
        uv = _uv()
    except RuntimeError as exc:
        say(f"error: {exc}")
        return 1
    plan.append(("reinstall the tool from the checkout",
                 [uv, "tool", "install", "--editable", str(source_dir()), "--reinstall"], None))
    if restart:
        plan.append(("restart running devices",
                     ["systemctl", "--user", "try-restart", "dizzy-store@*.service"], None))
    for label, command, _ in plan:
        say(f"-> {label}: {' '.join(command)}")
        if dry_run:
            continue
        try:
            result = runner(command)
        except OSError as exc:
            say(f"error: could not run {command[0]}: {exc}")
            return 1
        if result.returncode != 0:
            say(f"error: {label} failed (exit {result.returncode})")
            return result.returncode or 1
    if not dry_run:
        exe = shutil.which("dizzy-store")
        if exe:
            say("-> now running:")
            runner([exe, "version"])
    return 0
