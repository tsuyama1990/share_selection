import time
from collections import deque
from collections.abc import Callable

SECONDS_PER_MINUTE = 60


class RateLimiter:
    """Sliding window: at most ``max_calls`` per ``window_s`` seconds; ``acquire`` sleeps when full."""

    def __init__(
        self,
        max_calls: int,
        window_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._max_calls, self._window_s, self._clock, self._sleep = max_calls, window_s, clock, sleep
        self._stamps: deque[float] = deque()

    @classmethod
    def per_minute(cls, max_calls: int) -> "RateLimiter":
        return cls(max_calls, SECONDS_PER_MINUTE)

    def acquire(self) -> None:
        now = self._clock()
        while self._stamps and now - self._stamps[0] >= self._window_s:
            self._stamps.popleft()
        if len(self._stamps) >= self._max_calls:
            self._sleep(self._window_s - (now - self._stamps[0]))
            self._stamps.popleft()
        self._stamps.append(self._clock())
