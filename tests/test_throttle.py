"""Tests for throttle.py: machine-wide pacing of API requests shared by
every run of the tool (see
https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/17).
conftest.py points throttle.LOCK_FILE at a per-test temp path."""

import subprocess
import sys
from pathlib import Path

import pytest

import throttle

REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeClock:
    """Stands in for time.time/time.sleep inside throttle: sleeping
    advances the clock instead of actually waiting, and every sleep is
    recorded so tests can assert how long a run would have waited."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(throttle.time, "time", fake.time)
    monkeypatch.setattr(throttle.time, "sleep", fake.sleep)
    return fake


def test_first_request_does_not_wait(clock):
    throttle.wait_for_turn(0.5)
    assert clock.sleeps == []


def test_back_to_back_requests_are_spaced_by_interval(clock):
    throttle.wait_for_turn(0.5)
    throttle.wait_for_turn(0.5)
    throttle.wait_for_turn(0.5)
    assert clock.sleeps == pytest.approx([0.5, 0.5])


def test_no_wait_once_interval_has_passed(clock):
    throttle.wait_for_turn(0.5)
    clock.now += 2.0
    throttle.wait_for_turn(0.5)
    assert clock.sleeps == []


def test_back_off_delays_next_request(clock):
    throttle.back_off(10.0)
    throttle.wait_for_turn(0.5)
    assert clock.sleeps == pytest.approx([10.0])


def test_shorter_back_off_never_shortens_existing_reservation(clock):
    throttle.back_off(10.0)
    throttle.back_off(1.0)
    throttle.wait_for_turn(0.5)
    assert clock.sleeps == pytest.approx([10.0])


def test_back_off_is_capped(clock):
    throttle.back_off(throttle.MAX_WAIT_SECONDS * 10)
    throttle.wait_for_turn(0.5)
    assert clock.sleeps == pytest.approx([throttle.MAX_WAIT_SECONDS])


@pytest.mark.parametrize("content", [b"", b"not a number", b"\xff\xfe\x00"])
def test_garbage_lock_file_counts_as_no_reservation(clock, content):
    throttle.LOCK_FILE.write_bytes(content)
    throttle.wait_for_turn(0.5)
    assert clock.sleeps == []


def test_far_future_reservation_is_ignored(clock):
    # e.g. left behind before the system clock was turned back -- must
    # not stall every later run for hours.
    far_future = clock.now + throttle.MAX_WAIT_SECONDS * 100
    throttle.LOCK_FILE.write_text(f"{far_future:.6f}", encoding="ascii")
    throttle.wait_for_turn(0.5)
    assert clock.sleeps == []


_WORKER = """
import sys, time
from pathlib import Path
import throttle
throttle.LOCK_FILE = Path(sys.argv[1])
print(time.time(), flush=True)
for _ in range(int(sys.argv[2])):
    throttle.wait_for_turn(float(sys.argv[3]))
    print(time.time(), flush=True)
"""


def test_concurrent_processes_share_one_request_rate(tmp_path):
    """Several real processes pacing against the same lock file must
    together stay within one request per interval. Each worker prints
    its start time, then a timestamp after every granted request. With
    N requests in total, the last one can't be granted earlier than
    (N - 1) intervals after the earliest start -- whereas independently
    paced processes would all finish after only (per-worker - 1)
    intervals."""
    lock_file = tmp_path / "shared.lock"
    n_workers, per_worker, interval = 3, 3, 0.2
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", _WORKER, str(lock_file), str(per_worker)]
            + [str(interval)],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(n_workers)
    ]
    starts, grants = [], []
    for worker in workers:
        out, _ = worker.communicate(timeout=60)
        assert worker.returncode == 0
        stamps = [float(line) for line in out.split()]
        starts.append(stamps[0])
        grants.extend(stamps[1:])

    n_requests = n_workers * per_worker
    assert len(grants) == n_requests
    assert max(grants) - min(starts) >= (n_requests - 1) * interval - 0.01


def test_lock_file_is_created_on_first_use(clock):
    assert not throttle.LOCK_FILE.exists()
    throttle.wait_for_turn(0.5)
    assert throttle.LOCK_FILE.exists()
