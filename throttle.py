"""Machine-wide pacing of requests to the Wikipedia API.

Every run of this tool on the same machine shares one request budget:
before each API request, a run reserves the next free time slot in a
small lock file and sleeps until that slot comes up. Several concurrent
runs therefore each get slower instead of multiplying the load on
de.wikipedia.org (see
https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/17).
"""

import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Lives in the system temp folder rather than next to cache.json, so
# runs from different working directories or clones of this repository
# are paced together too.
LOCK_FILE = Path(tempfile.gettempdir()) / "WikipediaTemplateChecker-api.lock"

# Minimum time between two API requests, across all runs on this machine.
MIN_INTERVAL_SECONDS = 0.5

# Upper bound for any single wait. Guards against a reservation that
# lies absurdly far in the future (e.g. after the system clock was
# turned back, or a huge Retry-After header) stalling every run.
MAX_WAIT_SECONDS = 300.0

# Fixed width of the stored timestamp, so rewriting it never needs to
# truncate the file (see _write_next_allowed).
_FIELD_WIDTH = 24


@contextmanager
def _locked_state() -> Iterator[int]:
    """Opens LOCK_FILE and holds an exclusive OS-level lock on it for
    the duration of the block, yielding the file descriptor. An OS lock
    (rather than a "lock file exists" convention with a PID inside) is
    released automatically if the process crashes or is killed, so a
    dead run can never leave every later run stuck."""
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        _acquire(fd)
        try:
            yield fd
        finally:
            _release(fd)
    finally:
        os.close(fd)


if sys.platform == "win32":
    import msvcrt

    def _acquire(fd: int) -> None:
        # LK_LOCK gives up with an OSError after ~10 seconds, so poll
        # with the non-blocking variant instead. The lock is only ever
        # held for a quick read-modify-write, so this rarely loops.
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.01)

    def _release(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_next_allowed(fd: int, now: float) -> float:
    """Returns the epoch time at which the next request is allowed, as
    stored in the lock file. An empty or unreadable file (first run, or
    garbage) and a value more than MAX_WAIT_SECONDS in the future both
    count as "no reservation" -- the file is only a coordination hint,
    never a reason to fail or hang a run."""
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.read(fd, _FIELD_WIDTH)
    try:
        next_allowed = float(raw.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        return 0.0
    if next_allowed > now + MAX_WAIT_SECONDS:
        return 0.0
    return next_allowed


def _write_next_allowed(fd: int, next_allowed: float) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{next_allowed:<{_FIELD_WIDTH}.6f}".encode("ascii"))


def wait_for_turn(min_interval: float = MIN_INTERVAL_SECONDS) -> None:
    """Blocks until this run may send its next API request. Reserves the
    earliest free slot (at least `min_interval` after the previous
    reservation by any run) and only then sleeps, outside the lock --
    holding the lock while sleeping would make every other run wait for
    the lock instead of queueing up their own slots."""
    with _locked_state() as fd:
        now = time.time()
        slot = max(_read_next_allowed(fd, now), now)
        _write_next_allowed(fd, slot + min_interval)
    if slot > now:
        time.sleep(slot - now)


def back_off(seconds: float) -> None:
    """Pushes the next allowed request, for every run on this machine,
    at least `seconds` into the future -- e.g. after the API answered
    429 Too Many Requests or a maxlag error, which is a signal about
    the server's load, not just about this one run. Never shortens a
    reservation that already reaches further out."""
    seconds = min(seconds, MAX_WAIT_SECONDS)
    with _locked_state() as fd:
        now = time.time()
        next_allowed = max(_read_next_allowed(fd, now), now + seconds)
        _write_next_allowed(fd, next_allowed)
