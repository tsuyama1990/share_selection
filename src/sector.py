"""Sector medians of a run's tickers and the comparison of one ticker with its sector."""

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any


@dataclass(frozen=True)
class Peers:
    medians: dict[str, dict[str, float | None]]  # sector -> metric -> median
    sectors: dict[str, str]  # ticker -> sector
    metrics: list[str]


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
