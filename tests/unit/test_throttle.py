from src.throttle import RateLimiter


def test_rate_limiter_sleeps_when_window_is_full():
    now = [0.0]
    slept: list[float] = []
    limiter = RateLimiter(2, 60, clock=lambda: now[0], sleep=slept.append)
    limiter.acquire()
    now[0] = 10
    limiter.acquire()
    limiter.acquire()
    assert slept == [50]
    now[0] = 200
    limiter.acquire()
    assert slept == [50]
