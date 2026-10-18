"""Sector medians of a run's tickers and the comparison of one ticker with its sector."""

import datetime
import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import mean, median
from typing import Any

import pandas as pd

from .records import RecordStore


@dataclass(frozen=True)
class Universe:
    history: Callable[[str], pd.Series]
    tickers: Sequence[str]
    sectors: dict[str, str]


@dataclass(frozen=True)
class MomentumSettings:
    months: int
    note_top_share: float
    note_position: float

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "MomentumSettings":
        sec = cfg["sector"]
        return cls(sec["momentum_months"], sec["momentum_note_top_share"], sec["momentum_note_position"])


@dataclass(frozen=True)
class Peers:
    medians: dict[str, dict[str, float | None]]  # sector -> metric -> median
    sectors: dict[str, str]  # ticker -> sector
    metrics: list[str]
    tickers: tuple[str, ...] = ()  # every ticker of the run

    @classmethod
    def from_run(cls, records: RecordStore, run_id: str, sectors: dict[str, str], cfg: dict[str, Any]) -> "Peers":
        """Sector medians over every ticker of the run."""
        sec = cfg["sector"]
        metrics = records.run_metrics(run_id)
        medians = sector_medians(metrics, sectors, sec["metrics"], sec["min_peers"])
        return cls(medians, sectors, sec["metrics"], tuple(metrics))


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def sector_medians(
    metrics_by_ticker: dict[str, dict[str, Any]], sectors: dict[str, str], metrics: list[str], min_peers: int
) -> dict[str, dict[str, float | None]]:
    """Median of each metric per sector over all given tickers; None with fewer than ``min_peers`` numeric values."""
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: {m: [] for m in metrics})
    for ticker, row in metrics_by_ticker.items():
        if ticker in sectors:
            for metric in metrics:
                if _is_number(row.get(metric)):
                    values[sectors[ticker]][metric].append(row[metric])
    return {
        sector: {m: median(v) if len(v) >= min_peers else None for m, v in by_metric.items()}
        for sector, by_metric in values.items()
    }


def compare(ticker: str, row: dict[str, Any], peers: Peers) -> dict[str, Any]:
    """The ticker's sector and, per metric, its value, the sector median and their ratio (None without a usable one)."""
    sector = peers.sectors.get(ticker)
    medians = peers.medians.get(sector, {}) if sector else {}
    result = {}
    for metric in peers.metrics:
        value = row[metric] if _is_number(row.get(metric)) else None
        med = medians.get(metric)
        result[metric] = {"value": value, "median": med, "ratio": value / med if value is not None and med else None}
    return {"sector": sector, "metrics": result}


def _period_return(series: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    series = series.dropna()
    series.index = pd.to_datetime(series.index)
    series = series.sort_index()
    base = series[series.index <= end]
    begin = series[series.index <= start]
    if base.empty or begin.empty:
        return None
    start_price = float(begin.iloc[-1])
    return None if start_price == 0 else float(base.iloc[-1]) / start_price - 1


def _ranks(values: dict[str, float]) -> dict[str, int]:
    """1 for the highest value; ties share the smallest rank."""
    ranks: dict[str, int] = {}
    previous: float | None = None
    current = 0
    for position, (key, value) in enumerate(sorted(values.items(), key=lambda item: item[1], reverse=True), 1):
        if previous is None or value != previous:
            current = position
            previous = value
        ranks[key] = current
    return ranks


def momentum(universe: Universe, target: str, settings: MomentumSettings, today: datetime.date) -> dict[str, Any]:
    """The target's industry excess return, rank among industries and position in its industry."""
    start = pd.Timestamp(today) - pd.DateOffset(months=settings.months)
    end = pd.Timestamp(today)
    returns: dict[str, float] = {}
    for ticker in dict.fromkeys(universe.tickers):
        sector = universe.sectors.get(ticker)
        if sector is None:
            continue
        period = _period_return(universe.history(ticker), start, end)
        if period is not None:
            returns[ticker] = period
    by_sector: dict[str, list[float]] = defaultdict(list)
    for ticker, period in returns.items():
        by_sector[universe.sectors[ticker]].append(period)
    excess: dict[str, float] = {}
    if returns:
        market = mean(returns.values())
        excess = {sector: mean(values) - market for sector, values in by_sector.items()}
    ranks = _ranks(excess)
    target_sector = universe.sectors.get(target)
    position: float | None = None
    if target in returns and target_sector is not None:
        values = by_sector[target_sector]
        position = (sum(1 for value in values if value > returns[target]) + 1) / len(values)
    return {
        "months": settings.months,
        "industry_excess": excess.get(target_sector) if target_sector is not None else None,
        "industry_rank": ranks.get(target_sector) if target_sector is not None else None,
        "industries": len(excess),
        "position": position,
    }


def momentum_note(momentum: dict[str, Any], settings: MomentumSettings) -> bool:
    """True when the industry is in the top share and the target is in the lower half of it."""
    rank = momentum.get("industry_rank")
    industries = momentum.get("industries")
    position = momentum.get("position")
    if rank is None or not industries or position is None:
        return False
    return rank / industries <= settings.note_top_share and position > settings.note_position
