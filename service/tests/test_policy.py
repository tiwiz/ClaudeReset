"""The polling policy is the part that talks to Anthropic: it must be boring and predictable."""

import random

from app.poller import compute_delay


def test_base_interval_with_jitter_stays_in_range():
    rng = random.Random(1)
    for _ in range(50):
        delay = compute_delay(base=300, jitter=20, error_count=0, reset_in=None, rng=rng)
        assert 280 <= delay <= 320


def test_never_below_the_floor():
    rng = random.Random(2)
    assert compute_delay(base=10, jitter=0, error_count=0, reset_in=None, rng=rng) >= 60


def test_backoff_ladder():
    rng = random.Random(3)
    ladder = [60, 120, 300, 600, 1800, 1800]
    for index, expected in enumerate(ladder, start=1):
        assert compute_delay(base=300, jitter=0, error_count=index, reset_in=None, rng=rng) == expected


def test_reset_is_followed_quickly():
    # 40 s to the reset, and the normal interval is 5 minutes: wake up right after the reset.
    delay = compute_delay(base=300, jitter=0, error_count=0, reset_in=40, rng=random.Random(4))
    assert 40 < delay <= 60


def test_far_reset_does_not_change_the_interval():
    delay = compute_delay(base=300, jitter=0, error_count=0, reset_in=9000, rng=random.Random(5))
    assert delay == 300


def test_backoff_wins_over_reset():
    # While backing off we still do not want to ignore a reset that is about to happen.
    delay = compute_delay(base=300, jitter=0, error_count=3, reset_in=100, rng=random.Random(6))
    assert delay == 105
