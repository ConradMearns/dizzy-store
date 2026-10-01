"""`update` and `version`: the recipe for updating an editable install, and what says what is running."""
import subprocess
from pathlib import Path

import pytest

from dizzy_store import tool


class Runner:
    """A stand-in for subprocess.run that records commands and answers the git probes."""

    def __init__(self, dirty=False, fail_on=None, repo="/repo"):
        self.calls, self.dirty, self.fail_on, self.repo = [], dirty, fail_on, repo

    def __call__(self, command, **kw):
        self.calls.append(command)
        out = ""
        if command[0] == "git" and "rev-parse" in command and "--show-toplevel" in command:
            out = self.repo
        elif command[0] == "git" and "status" in command:
            out = " M host/engine.py\n" if self.dirty else ""
        code = 3 if self.fail_on and self.fail_on in command else 0
        return subprocess.CompletedProcess(command, code, out, "")

    def steps(self):
        return [c for c in self.calls if not (c[0] == "git" and ("rev-parse" in c or "status" in c))]


def say_into(lines):
    return lambda text: lines.append(text)


def test_update_reinstalls_from_the_checkout_then_restarts_devices(monkeypatch):
    monkeypatch.setattr(tool, "_uv", lambda: "/usr/bin/uv")
    run, lines = Runner(), []
    assert tool.update(runner=run, say=say_into(lines)) == 0
    steps = run.steps()
    assert steps[0] == ["/usr/bin/uv", "tool", "install", "--editable", str(tool.source_dir()), "--reinstall"]
    assert steps[1] == ["systemctl", "--user", "try-restart", "dizzy-store@*.service"]
    assert all(c[0] != "git" for c in steps)                  # no pull unless asked


def test_pull_goes_first_and_only_over_a_clean_tree(monkeypatch):
    monkeypatch.setattr(tool, "_uv", lambda: "/usr/bin/uv")
    run = Runner()
    assert tool.update(pull=True, runner=run, say=lambda _: None) == 0
    assert run.steps()[0] == ["git", "-C", "/repo", "pull", "--ff-only"]
    assert run.steps()[1][0] == "/usr/bin/uv"
    dirty, lines = Runner(dirty=True), []
    assert tool.update(pull=True, runner=dirty, say=say_into(lines)) == 1
    assert dirty.steps() == []                                # nothing was touched
    assert "uncommitted changes" in lines[0]


def test_no_restart_and_dry_run(monkeypatch):
    monkeypatch.setattr(tool, "_uv", lambda: "/usr/bin/uv")
    run = Runner()
    tool.update(restart=False, runner=run, say=lambda _: None)
    assert not any(c[0] == "systemctl" for c in run.steps())
    dry, lines = Runner(), []
    assert tool.update(dry_run=True, runner=dry, say=say_into(lines)) == 0
    assert dry.steps() == [] and any("tool install" in l for l in lines)       # shown, not run


def test_a_failing_step_stops_the_update(monkeypatch):
    monkeypatch.setattr(tool, "_uv", lambda: "/usr/bin/uv")
    run, lines = Runner(fail_on="--reinstall"), []
    assert tool.update(runner=run, say=say_into(lines)) == 3
    assert not any(c[0] == "systemctl" for c in run.steps())   # never restart onto a half-updated install
    assert any("failed" in l for l in lines)


def test_a_missing_uv_is_an_error_not_a_traceback(monkeypatch, tmp_path):
    monkeypatch.setattr(tool.shutil, "which", lambda name: None)
    monkeypatch.setattr(tool.Path, "home", lambda: tmp_path)
    lines = []
    assert tool.update(runner=Runner(), say=say_into(lines)) == 1
    assert "uv" in lines[0]


def test_pull_needs_a_git_checkout(monkeypatch):
    monkeypatch.setattr(tool, "_uv", lambda: "/usr/bin/uv")
    lines = []
    run = Runner(repo="")
    run_ = lambda command, **kw: subprocess.CompletedProcess(command, 128, "", "not a repo")
    assert tool.update(pull=True, runner=run_, say=say_into(lines)) == 1
    assert "git checkout" in lines[0]


# ── version ──────────────────────────────────────────────────────────────────

def test_version_info_names_what_is_running():
    info = tool.version_info()
    assert info["dizzy-store"] and Path(info["source"]).name == "store"
    assert len(info["read models"]) == 16
    assert "commit" in info and "python" in info


def test_commit_describes_a_checkout_and_a_non_checkout(tmp_path):
    assert tool._commit(tmp_path) == "(not a git checkout)"
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"], ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=tmp_path, check=True)
    (tmp_path / "f").write_text("a")
    subprocess.run(["git", "add", "f"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=tmp_path, check=True)
    assert "clean" in tool._commit(tmp_path)
    (tmp_path / "f").write_text("b")
    assert "uncommitted changes" in tool._commit(tmp_path)
