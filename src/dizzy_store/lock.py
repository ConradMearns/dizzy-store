"""One daemon per store, enforced by the operating system.

Two processes acting on one store is the failure that cannot be allowed: each folds only the events
IT appended into its own read models, both believe they are the only writer, and the first thing a
person notices is a store that disagrees with itself. A portable drive makes it easy to do by
accident — started by hand while a service already runs it, or plugged into a second terminal.

`flock` on <root>/.store/daemon.lock: held for as long as the process lives, released by the kernel
the instant it dies (no stale lock files, no pid races), and visible to every other process on the
machine. The pid inside is only there so the message can name the other process.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Optional

from .config import ConfigError


class StoreBusy(ConfigError):
    """Another process is already running this store. Exit 78: restarting will not fix it."""


class StoreLock:
    def __init__(self, state_dir: str | Path):
        self.path = Path(state_dir) / "daemon.lock"
        self._fd: Optional[int] = None

    def acquire(self) -> "StoreLock":
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = os.pread(fd, 32, 0).decode(errors="replace").strip() or "?"
            os.close(fd)
            raise StoreBusy(f"another dizzy-store (pid {holder}) is already running {self.path.parent.parent} — "
                            "stop it first (`systemctl --user stop dizzy-store@NAME`)") from None
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return self

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "StoreLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
