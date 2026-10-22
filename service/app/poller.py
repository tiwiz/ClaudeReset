"""Background refresher and cache.

Design rules, in order of importance:

1. HTTP handlers never wait for Anthropic: they always answer from the cache.
2. One upstream fetch at a time, never parallel.
3. Be polite: 5 minutes by default with jitter, exponential backoff on errors, and an extra
   fetch right after a quota window resets (the only moment the numbers really move).
4. The access token is refreshed only when it is about to expire, or once after a 401.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable

from . import config
from .claude import ClaudeClient, ClaudeError, parse_usage

# On failures we slow down instead of hammering: 1, 2, 5, 10, 30 minutes, then steady.
BACKOFF_STEPS = (60, 120, 300, 600, 1800)


def compute_delay(
    *,
    base: int,
    jitter: int,
    error_count: int,
    reset_in: float | None,
    rng: random.Random | None = None,
    min_seconds: int = 60,
    max_backoff: int = 1800,
    backoff_steps: tuple[int, ...] = BACKOFF_STEPS,
) -> float:
    """Seconds to wait before the next upstream fetch.

    Pure function on purpose: the whole policy is testable without a network or a clock.
    """
    rng = rng or random
    if error_count:
        step = backoff_steps[min(error_count, len(backoff_steps)) - 1]
        delay = float(min(step, max_backoff))
    else:
        delay = float(max(min_seconds, base + rng.randint(-jitter, jitter) if jitter else base))
    # A window reset is the one moment the numbers move: wake up just after it.
    if reset_in is not None and 0 < reset_in <= delay + 30:
        delay = max(min_seconds / 2, reset_in + 5)
    return float(delay)


class UsagePoller:
    def __init__(
        self,
        client: ClaudeClient,
        store,
        *,
        base: int = config.POLL_SECONDS,
        jitter: int = config.JITTER_SECONDS,
        min_seconds: int = config.MIN_POLL_SECONDS,
        stale: int = config.STALE_SECONDS,
        refresh_margin: int = config.REFRESH_MARGIN_SECONDS,
        manual_min_interval: int = config.MANUAL_REFRESH_MIN_INTERVAL,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.client = client
        self.store = store
        self.base = base
        self.jitter = jitter
        self.min_seconds = min_seconds
        self.stale = stale
        self.refresh_margin = refresh_margin
        self.manual_min_interval = manual_min_interval
        self.rng = rng or random.Random()
        self.clock = clock
        self._sleep = sleeper
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.error_count = 0
        self.error = ""
        self.data: dict[str, Any] = {}
        self.fetched_at: float | None = None
        self.last_attempt_at: float | None = None
        self.last_token_refresh_at: float | None = None
        self.next_fetch_at: float | None = None
        self._force = threading.Event()

    # -- state -----------------------------------------------------------
    def tokens(self) -> dict[str, Any]:
        with self._lock:
            try:
                return self.store.load()
            except Exception as exc:  # noqa: BLE001 - a broken volume must not take the API down
                self.error = str(exc)[:200]
                return {}

    def logged_in(self) -> bool:
        tok = self.tokens()
        return bool(tok.get("access_token") or tok.get("refresh_token"))

    def access_token_valid(self) -> bool:
        tok = self.tokens()
        expires = tok.get("access_expires_at")
        if not tok.get("access_token"):
            return False
        if not expires:
            return True
        return expires - self.clock() > 0

    def age(self) -> float | None:
        if self.fetched_at is None:
            return None
        return max(0.0, self.clock() - self.fetched_at)

    # -- the compact contract the display consumes ------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = dict(self.data)
            age = self.age()
            stale = age is None or age > self.stale
            ok = bool(data) and not stale and not self.error
            reset = data.get("r")
            reset7 = data.get("r7")
            now = self.clock()
            reason = self.error
            if not reason and not self.logged_in():
                reason = "non autenticato"
            return {
                "v": 1,
                "ok": 1 if ok else 0,
                "p": data.get("p"),
                "r": int(reset - now) if reset else None,
                "p7": data.get("p7"),
                "r7": int(reset7 - now) if reset7 else None,
                "age": int(age) if age is not None else None,
                "stale": 1 if stale else 0,
                "err": reason[:120],
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            tok = self.tokens()
            now = self.clock()
            return {
                "version": 1,
                "logged_in": self.logged_in(),
                "account": tok.get("account") or {},
                "organization": tok.get("organization") or {},
                "scope": tok.get("scope"),
                "access_expires_at": tok.get("access_expires_at"),
                "refresh_expires_at": tok.get("refresh_expires_at"),
                "refresh_expiry_known": bool(tok.get("refresh_expires_at")),
                "response_keys": tok.get("response_keys") or [],
                "fetched_at": self.fetched_at,
                "age": int(self.age()) if self.age() is not None else None,
                "stale": (self.age() is None or self.age() > self.stale),
                "error": self.error,
                "error_count": self.error_count,
                "poll_seconds": self.base,
                "next_fetch_in": int(self.next_fetch_at - now) if self.next_fetch_at else None,
                "last_token_refresh_at": self.last_token_refresh_at,
                "usage": {
                    k: (int(v) if k.startswith("r") and isinstance(v, float) else v)
                    for k, v in self.data.items()
                },
                "usage_age": int(self.age()) if self.age() is not None else None,
            }

    # -- fetching --------------------------------------------------------
    def _ensure_access_token(self, *, force: bool = False) -> str:
        tok = self.tokens()
        access = tok.get("access_token")
        expires = tok.get("access_expires_at")
        needs_refresh = force or not access or (expires and expires - self.clock() < self.refresh_margin)
        if not needs_refresh:
            return access
        refresh_token = tok.get("refresh_token")
        if not refresh_token:
            raise ClaudeError("sessione scaduta: serve un nuovo accesso")
        refreshed = self.client.refresh(refresh_token)
        saved = self.store.save_token_response(refreshed, previous=tok)
        self.last_token_refresh_at = self.clock()
        if not saved.get("access_token"):
            raise ClaudeError("il refresh non ha restituito un access token")
        return saved["access_token"]

    def fetch_once(self) -> bool:
        with self._lock:
            self.last_attempt_at = self.clock()
            if not self.logged_in():
                self.error = "non autenticato"
                self.error_count = 0
                return False
            try:
                token = self._ensure_access_token()
                payload = self.client.fetch_usage(token)
            except ClaudeError as exc:
                if exc.status == 401:
                    try:
                        token = self._ensure_access_token(force=True)
                        payload = self.client.fetch_usage(token)
                    except ClaudeError as exc2:
                        self._record_failure(exc2)
                        return False
                else:
                    self._record_failure(exc)
                    return False
            except Exception as exc:  # noqa: BLE001
                self._record_failure(ClaudeError(f"{type(exc).__name__}: {exc}"))
                return False

            self.data = parse_usage(payload)
            self.fetched_at = self.clock()
            self.error = ""
            self.error_count = 0
            return True

    def _record_failure(self, exc: Exception) -> None:
        self.error = str(exc)[:200]
        self.error_count += 1

    def refresh_now(self) -> bool:
        with self._lock:
            if self.last_attempt_at and self.clock() - self.last_attempt_at < self.manual_min_interval:
                return False
        return self.fetch_once()

    def run_forever(self) -> None:
        while not self._stop.is_set():
            if self.logged_in():
                self.fetch_once()
            reset_in = None
            with self._lock:
                if self.data.get("r"):
                    reset_in = self.data["r"] - self.clock()
            delay = compute_delay(
                base=self.base,
                jitter=self.jitter,
                error_count=self.error_count,
                reset_in=reset_in,
                rng=self.rng,
                min_seconds=self.min_seconds,
            )
            self.next_fetch_at = self.clock() + delay
            self._force.wait(delay)
            self._force.clear()
            self._stop.clear()

    def stop(self) -> None:
        self._stop.set()
        self._force.set()
