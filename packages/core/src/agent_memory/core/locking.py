"""Pipeline-level serialization. Every writer passes through one advisory lock."""

from __future__ import annotations

import contextlib
import fcntl
import pathlib
import time
from collections.abc import Iterator

from .config import COORDINATION_LOCK_POLL_SECONDS
from .errors import LockTimeoutError
from .paths import StoreLayout


@contextlib.contextmanager
def file_lock(
    path: pathlib.Path,
    *,
    shared: bool = False,
    timeout: float | None = None,
    poll: float = COORDINATION_LOCK_POLL_SECONDS,
) -> Iterator[None]:
    """Advisory cross-process lock for coordination state, independent of Store writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    deadline = None if timeout is None else time.monotonic() + timeout
    with path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), operation | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise LockTimeoutError(f"coordination lock busy for {timeout}s") from None
                time.sleep(poll)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def lock_is_held(path: pathlib.Path) -> bool:
    """Probe an advisory lock. This is paired with a lease; it is not a PID liveness check."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False


@contextlib.contextmanager
def store_lock(layout: StoreLayout) -> Iterator[None]:
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    timeout = layout.config.storage.lock_timeout_seconds
    poll = layout.config.storage.lock_poll_seconds
    deadline = time.monotonic() + timeout
    with layout.lock_file.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(f"store lock busy for {timeout}s") from None
                time.sleep(poll)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
