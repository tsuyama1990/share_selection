"""Outcomes of recorded runs: the return of each ticker, and its excess over a benchmark, after each horizon."""

import datetime
from collections.abc import Callable, Iterable, Sequence
from functools import partial
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from . import fields as F
from .flow_store import FlowStore, OutcomeRow
from .records import RecordStore
from .tickers import read_column
from .yahoo import YahooClient


def _close_on_or_before(closes: pd.Series, date: pd.Timestamp) -> float | None:
    past = closes.loc[:date]
    return float(past.iloc[-1]) if len(past) else None


def _change(p0: float | None, p1: float | None) -> float | None:
    return None if p0 is None or p1 is None else p1 / p0 - 1


def _history_cache(history: Callable[[str], pd.Series]) -> Callable[[str], pd.Series]:
    """Memoise ``history`` so each ticker's series is loaded once; a failed fetch becomes an empty series."""
    closes: dict[str, pd.Series] = {}

    def get(ticker: str) -> pd.Series:
        if ticker not in closes:
            try:
                closes[ticker] = history(ticker)
            except Exception as e:
                print(f"History failed {ticker}: {e}")
                closes[ticker] = pd.Series(dtype=float)
        return closes[ticker]

    return get


def _ticker_return(get: Callable[[str], pd.Series], ticker: str, t0: pd.Timestamp, t1: pd.Timestamp) -> float | None:
    return _change(_close_on_or_before(get(ticker), t0), _close_on_or_before(get(ticker), t1))


def _returns(
    tickers: Iterable[str], get: Callable[[str], pd.Series], t0: pd.Timestamp, t1: pd.Timestamp
) -> list[float]:
    """The returns of the tickers that have both closes."""
    return [r for r in (_ticker_return(get, t, t0, t1) for t in tickers) if r is not None]


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
    get = _history_cache(history)
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


def evaluate_decisions(
    flows: FlowStore,
    history: Callable[[str], pd.Series],
    controls: Callable[[str, datetime.date], Sequence[str]],
    months: Sequence[int],
    today: datetime.datetime,
) -> int:
    """Store outcomes for each decision whose horizon (one of ``months``) has elapsed; returns the rows added.

    The excess of a decision is its return over the equal-weight mean of every ticker under test (the decisions and
    their control companies). The control excess is the mean return of the control companies over the same
    benchmark. ``history(ticker)`` gives adjusted daily closes; ``controls(ticker, date)`` gives the same-sector
    laggards to compare against.
    """
    get = _history_cache(history)
    due = [
        (row, pd.Timestamp(row.decided_at).normalize(), h)
        for h in months
        for row in flows.due_decisions(h, today.date())
    ]
    if not due:
        return 0
    control_of = {(row.ticker, t0): list(controls(row.ticker, t0.date())) for row, t0, _ in due}
    universe = {row.ticker for row, _, _ in due} | {t for ts in control_of.values() for t in ts}
    added = 0
    for row, t0, h in due:
        t1 = t0 + pd.DateOffset(months=h)
        ret = _ticker_return(get, row.ticker, t0, t1)
        rets = _returns(universe, get, t0, t1)
        bench = sum(rets) / len(rets) if rets else None
        ctl_rets = _returns(control_of[(row.ticker, t0)], get, t0, t1)
        ctl_mean = sum(ctl_rets) / len(ctl_rets) if ctl_rets else None
        flows.record_outcome(
            OutcomeRow(
                row.flow_id,
                row.ticker,
                row.decided_at,
                h,
                None if ret is None or bench is None else ret - bench,
                None if ctl_mean is None or bench is None else ctl_mean - bench,
                len(ctl_rets),
            )
        )
        added += 1
    return added


def _select_controls(
    cfg: dict[str, Any], root: Path, store: RecordStore, history: Callable[[str], pd.Series]
) -> Callable[[str, datetime.date], list[str]]:
    """A closure that lists the same-sector companies of a ticker whose past gain and PBR are at or below the
    sector's median at the decision date."""
    sectors = read_column(root / cfg["system"]["input_csv"], "sector33")
    past = int(cfg["flow"]["control"]["past_months"])
    metrics = store.run_metrics(store.resolve_run(None))
    get = _history_cache(history)

    def sector_of(ticker: str) -> str | None:
        return sectors.get(ticker) or sectors.get(ticker.split(".")[0])

    def controls(ticker: str, date: datetime.date) -> list[str]:
        sector = sector_of(ticker)
        if sector is None:
            return []
        t1 = pd.Timestamp(date)
        t0 = t1 - pd.DateOffset(months=past)
        rows = []
        for other, m in metrics.items():
            if sector_of(other) != sector:
                continue
            gain = _ticker_return(get, other, t0, t1)
            pbr = m.get(F.PBR)
            if gain is not None and pbr is not None:
                rows.append((other, gain, pbr))
        if not rows:
            return []
        med_gain = median([r[1] for r in rows])
        med_pbr = median([r[2] for r in rows])
        return [t for t, g, p in rows if g <= med_gain and p <= med_pbr]

    return controls


def evaluate_recorded(cfg: dict[str, Any], root: Path, client: YahooClient, now: datetime.datetime) -> int:
    """`evaluate` and the recorded flow decisions whose horizons have elapsed; prices from the earliest run."""
    rec = cfg["records"]
    flow = cfg.get("flow")
    with RecordStore.from_config(cfg, root) as store:
        runs = store.runs()
        earliest = min((at for _, at in runs), default=now)
        start = (earliest - datetime.timedelta(days=rec["price_lookback_days"])).date()
        history = partial(client.adjusted_close, start=start)
        added = evaluate(store, history, rec["horizons_months"], rec["benchmark_ticker"], now)
        if not flow or not runs:
            return added
        with FlowStore.from_config(cfg, root) as flows:
            months = flow["outcome_months"]
            if not any(flows.due_decisions(m, now.date()) for m in months):
                return added  # the controls need the ticker list; build them only when a decision is due
            controls = _select_controls(cfg, root, store, history)
            added += evaluate_decisions(flows, history, controls, months, now)
    return added
