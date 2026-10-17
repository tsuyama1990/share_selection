"""Outcomes of recorded runs: the return of each ticker, and its excess over a benchmark, after each horizon."""

import datetime
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any

import pandas as pd

from .records import RecordStore
from .yahoo import YahooClient


def _close_on_or_before(closes: pd.Series, date: pd.Timestamp) -> float | None:
    past = closes.loc[:date]
    return float(past.iloc[-1]) if len(past) else None


def _change(p0: float | None, p1: float | None) -> float | None:
    return None if p0 is None or p1 is None else p1 / p0 - 1


def evaluate(
    store: RecordStore,
    history: Callable[[str], pd.Series],
    horizons: Sequence[int],
    benchmark: str,
    today: datetime.datetime,
) -> int:
    """Store outcomes for every run and horizon that has elapsed and has none yet; returns the rows added.

    ``history(ticker)`` gives adjusted daily closes (naive dates); price on a date = last close on or before it.
    """
    closes: dict[str, pd.Series] = {}

    def get(ticker: str) -> pd.Series:
        if ticker not in closes:
            try:
                closes[ticker] = history(ticker)
            except Exception as e:
                print(f"History failed {ticker}: {e}")
                closes[ticker] = pd.Series(dtype=float)
        return closes[ticker]

    added = 0
    for run_id, run_at in store.runs():
        t0 = pd.Timestamp(run_at).normalize()
        rows = []
        for h in horizons:
            t1 = t0 + pd.DateOffset(months=h)
            if t1 > pd.Timestamp(today) or store.has_outcomes(run_id, h):
                continue
            bench = _change(_close_on_or_before(get(benchmark), t0), _close_on_or_before(get(benchmark), t1))
            for ticker in store.tickers(run_id):
                p0, p1 = _close_on_or_before(get(ticker), t0), _close_on_or_before(get(ticker), t1)
                ret = _change(p0, p1)
                rows.append([ticker, h, p0, p1, ret, bench, None if ret is None or bench is None else ret - bench])
        if rows:
            store.add_outcomes(run_id, rows)
            added += len(rows)
    return added


def evaluate_recorded(cfg: dict[str, Any], root: Path, client: YahooClient, now: datetime.datetime) -> int:
    """`evaluate` over the runs in the record store; prices are fetched from the earliest run on."""
    rec = cfg["records"]
    with RecordStore.from_config(cfg, root) as store:
        earliest = min((at for _, at in store.runs()), default=now)
        start = (earliest - datetime.timedelta(days=rec["price_lookback_days"])).date()
        history = partial(client.adjusted_close, start=start)
        return evaluate(store, history, rec["horizons_months"], rec["benchmark_ticker"], now)
