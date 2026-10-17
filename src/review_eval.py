"""The quality gate of a model and prompt version: reviews of tickers with known answers are scored and judged."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import fields as F
from .review import ReviewDeps, ReviewSettings, review_candidates


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
    fallback_rows: int  # reviews answered (partly) by a provider other than the primary one
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
    results: list[tuple[EvalCase, bool]], review_rows: list[dict[str, Any]], thresholds: dict[str, Any], primary: str
) -> EvalResult:
    """Pass: hit rate and lowest verified ratio reach their minimums, parse failures stay within the cap, and every
    review was answered by the ``primary`` "<provider>/<model>" alone (the pass is recorded for its model)."""
    hits = sum(hit for _, hit in results)
    parse_failures = sum(row["status"] == F.ReviewStatus.BAD_JSON for row in review_rows)
    ratios = [row["verified_ratio"] for row in review_rows if row["status"] == F.ReviewStatus.OK]
    lowest = min(ratios, default=0.0)
    fallback_rows = sum(set(row["llm_providers"]) - {primary} != set() for row in review_rows)
    passed = (
        bool(results)
        and hits / len(results) >= thresholds["min_hit_rate"]
        and parse_failures <= thresholds["max_parse_failures"]
        and lowest >= thresholds["min_verified_ratio"]
        and not fallback_rows
    )
    return EvalResult(len(results), hits, parse_failures, lowest, fallback_rows, passed)


def combine(results: list[EvalResult]) -> EvalResult:
    """One result for repeated evaluations: passed only when every repetition passed."""
    return EvalResult(
        sum(r.cases for r in results),
        sum(r.hits for r in results),
        sum(r.parse_failures for r in results),
        min((r.min_verified_ratio for r in results), default=0.0),
        sum(r.fallback_rows for r in results),
        bool(results) and all(r.passed for r in results),
    )


@dataclass(frozen=True)
class EvalGate:
    thresholds: dict[str, Any]  # min_hit_rate, max_parse_failures, min_verified_ratio
    repeats: int
    primary: str  # "<provider>/<model>" every review must come from
    run_id: str  # repetition i is recorded under "<run_id>-<i>"


def evaluate_model(
    cases: list[EvalCase],
    candidates: list[tuple[str, dict[str, Any]]],
    settings: ReviewSettings,
    deps: ReviewDeps,
    gate: EvalGate,
) -> list[tuple[list[tuple[EvalCase, bool]], EvalResult]]:
    """Review the case tickers ``gate.repeats`` times; per repetition the scored cases and their judgement."""
    outcomes = []
    for i in range(1, gate.repeats + 1):
        run_id = f"{gate.run_id}-{i}"
        review_candidates(run_id, candidates, None, settings, deps)
        rows = deps.records.reviews(run_id)
        scored = [(c, score_case(c, rows[c.ticker])) for c in cases]
        outcomes.append((scored, judge(scored, list(rows.values()), gate.thresholds, gate.primary)))
    return outcomes
