"""Simple in-memory sliding-window limits for login and signup.

Per process, like the realtime hubs (the backend runs as one instance). Memory
stays bounded: expired keys are dropped as they are touched, and the oldest
keys go first when a limiter holds too many.
"""
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

ALL: list["RateLimiter"] = []


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int, max_keys: int = 10_000, clock=time.monotonic):
        self.limit, self.window, self.max_keys, self.clock = limit, window_seconds, max_keys, clock
        self.events: dict[str, deque] = {}
        self.lock = threading.RLock()
        ALL.append(self)

    def _recent(self, key, now):
        events = self.events.get(key)
        if events is None:
            return None
        while events and events[0] <= now - self.window:
            events.popleft()
        if not events:
            del self.events[key]
            return None
        return events

    def check(self, key: str):
        """Raise 429 when the key already used up its attempts in the window."""
        with self.lock:
            now = self.clock()
            events = self._recent(key, now)
            if events is not None and len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window - now) + 1)
                raise HTTPException(
                    status_code=429,
                    detail="Too many attempts, try again later",
                    headers={"Retry-After": str(retry_after)},
                )

    def record(self, key: str):
        with self.lock:
            now = self.clock()
            events = self._recent(key, now)
            if events is None:
                if len(self.events) >= self.max_keys:
                    self._evict(now)
                events = self.events[key] = deque()
            events.append(now)

    def hit(self, key: str):
        """check() then record(): for limits that count every attempt."""
        with self.lock:
            self.check(key)
            self.record(key)

    def reset(self, key: str):
        with self.lock:
            self.events.pop(key, None)

    def clear(self):
        with self.lock:
            self.events.clear()

    def _evict(self, now):
        for key in list(self.events):
            self._recent(key, now)
        while len(self.events) >= self.max_keys:
            self.events.pop(next(iter(self.events)))


# Failures count for login, every attempt counts for signup. Per-email limits
# cannot be dodged by changing address; the per-IP ones are generous because
# many people can share an address (and a forwarded header can be forged).
LOGIN_BY_EMAIL = RateLimiter(10, 15 * 60)
LOGIN_BY_IP = RateLimiter(60, 15 * 60)
SIGNUP_BY_EMAIL = RateLimiter(5, 60 * 60)
SIGNUP_BY_IP = RateLimiter(20, 60 * 60)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def reset_all():
    for limiter in ALL:
        limiter.clear()
