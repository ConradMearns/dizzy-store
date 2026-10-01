"""systemd's readiness protocol (sd_notify), without a dependency.

Under `Type=notify` systemd waits for READY=1 before it calls the unit started, so
`systemctl --user start dizzy-store@laptop && dizzy-store status` cannot race the daemon's
listener. Outside systemd ($NOTIFY_SOCKET unset) every call is a quiet no-op.
"""
from __future__ import annotations

import os
import socket
from typing import Mapping, Optional


def notify(message: str, env: Optional[Mapping[str, str]] = None) -> bool:
    """Send one datagram ("READY=1", "STATUS=…", "RELOADING=1", "STOPPING=1"). True if it was sent."""
    env = os.environ if env is None else env
    address = env.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):                 # an abstract socket
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as sock:
            sock.connect(address)
            sock.sendall(message.encode())
        return True
    except OSError:
        return False                            # a broken notify socket must never take the daemon down
