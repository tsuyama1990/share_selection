"""The quality gate of a model and prompt version: reviews of tickers with known answers are scored and judged."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import fields as F


@dataclass(frozen=True)
class EvalCase:
    ticker: str
    name: str
    task: str
    field: str
    expect_any: list[str]  # one of them in the answer item or a quote passes; empty: the item is not unknown
    basis: str


@dataclass(frozen=True)
class EvalResult:
    cases: int
    hits: int
    parse_failures: int
    min_verified_ratio: float
    passed: bool

    @property
    def hit_rate(self) -> float:
        return self.hits / self.cases if self.cases else 0.0


def load_eval_cases(path: Path) -> list[EvalCase]:
    with open(path, encoding="utf-8") as f:
        return [EvalCase(**case) for case in yaml.safe_load(f)["cases"]]


def score_case(case: EvalCase, review_row: dict[str, Any]) -> bool:
    """Whether the verified answer item, or a quote of a verified claim for it, holds an expected word."""
    answer = review_row["answers"].get(case.task, {}).get(case.field, F.UNKNOWN)
    if not case.expect_any:
        return answer != F.UNKNOWN
    quotes = [c["quote"] for c in review_row["evidence"].get(case.task, []) if c["field"] == case.field]
    return any(word in text for word in case.expect_any for text in [str(answer), *quotes])


def judge(
    results: list[tuple[EvalCase, bool]], review_rows: list[dict[str, Any]], thresholds: dict[str, Any]
) -> EvalResult:
    """Pass: hit rate and lowest verified ratio reach their minimums, parse failures stay within the cap."""
    hits = sum(hit for _, hit in results)
    parse_failures = sum(row["status"] == F.ReviewStatus.BAD_JSON for row in review_rows)
    ratios = [row["verified_ratio"] for row in review_rows if row["status"] == F.ReviewStatus.OK]
    lowest = min(ratios, default=0.0)
    passed = (
        bool(results)
        and hits / len(results) >= thresholds["min_hit_rate"]
        and parse_failures <= thresholds["max_parse_failures"]
        and lowest >= thresholds["min_verified_ratio"]
    )
    return EvalResult(len(results), hits, parse_failures, lowest, passed)
