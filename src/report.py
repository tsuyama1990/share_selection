"""CSV report and console summary of screening results."""

import datetime
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from . import fields as F
from .review_eval import EvalCase, EvalResult, combine


def write_failures(failures: dict[str, str], out_dir: Path, filename: str) -> Path:
    """Write the failed tickers and their errors to ``filename`` with ``{date}`` filled in."""
    path = out_dir / filename.format(date=datetime.date.today())
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(failures.items()), columns=["ticker", "error"]).to_csv(path, index=False, encoding="utf-8")
    return path


def write_report(results: list[dict[str, Any]], out_dir: Path, filename: str, columns: Sequence[str]) -> Path:
    """Write results (sorted by Priority_Rank) to ``filename`` with ``{date}`` filled in, print the candidates."""
    full = pd.DataFrame(results).sort_values(F.PRIORITY_RANK)
    df = full[[c for c in columns if c in full.columns]].copy()
    if F.QUALITY_FLAGS in df.columns:
        df[F.QUALITY_FLAGS] = df[F.QUALITY_FLAGS].map(",".join)

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename.format(date=today)
    df.to_csv(path, index=False, encoding="utf-8-sig")  # sig for Excel

    candidates = df[full[F.STAGE2_CANDIDATE]]
    print("\nAnalysis Complete!")
    print(f"Passed: {len(df)} stocks")
    print(f"Saved to: {path}")
    print(f"\nStage 2 Candidates ({len(candidates)}):")
    print(candidates.to_string(index=False))
    return path


def eval_line(r: EvalResult) -> str:
    return (
        f"{r.hits}/{r.cases} cases, {r.parse_failures} parse failures, "
        f"lowest verified ratio {r.min_verified_ratio:.2f}, {r.fallback_rows} answered by a fallback: "
        f"{'PASSED' if r.passed else 'FAILED'}"
    )


def format_eval(
    outcomes: list[tuple[list[tuple[EvalCase, bool]], EvalResult]], model: str
) -> tuple[list[str], EvalResult]:
    """The lines of a ``review-eval`` (cases per repetition, then the overall verdict) and the overall result."""
    lines = []
    for n, (scored, result) in enumerate(outcomes, 1):
        for case, hit in scored:
            mark = "hit " if hit else "MISS"
            lines.append(f"  {n}: {mark} {case.ticker} {case.task}.{case.field} {case.expect_any}: {case.basis}")
        lines.append(f"  {n}: {eval_line(result)}")
    overall = combine([result for _, result in outcomes])
    lines.append(f"review-eval {model}, {len(outcomes)} runs: {eval_line(overall)}")
    return lines, overall
