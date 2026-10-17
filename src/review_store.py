"""Reviews and review-eval results (their own DuckDB file, exported to the git-ignored ``review.export_dir``).

They quote web articles, so they stay out of the committed run records.
"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from . import fields as F

if TYPE_CHECKING:  # review_eval imports review, which imports this module
    from .review_eval import EvalResult

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS reviews (
        run_id TEXT, ticker TEXT, status TEXT, suggestion TEXT, source_type TEXT, reason_forgotten TEXT,
        answers JSON, evidence JSON, verified_ratio DOUBLE, needs_attention BOOLEAN, sector_comparison JSON,
        doc_ids JSON, llm_providers JSON, prompt_version TEXT, reviewed_at TIMESTAMP, PRIMARY KEY (run_id, ticker))""",
    """CREATE TABLE IF NOT EXISTS review_evals (
        prompt_version TEXT, model TEXT, passed BOOLEAN, hit_rate DOUBLE, parse_failures INTEGER,
        min_verified_ratio DOUBLE, "at" TIMESTAMP, summary JSON)""",
)


@dataclass(frozen=True)
class ReviewRow:
    ticker: str
    status: F.ReviewStatus
    suggestion: str | None
    source_type: str | None
    reason_forgotten: str | None
    answers: dict[str, dict[str, Any]]  # task -> verified answer
    evidence: dict[str, list[dict[str, str]]]  # task -> verified claims
    verified_ratio: float
    needs_attention: bool
    sector_comparison: dict[str, Any] | None
    doc_ids: list[str]
    llm_providers: list[str]
    prompt_version: str


class ReviewStore:
    """Reviews and eval results in ``db_path``; each write is also exported as Parquet to ``export_dir``."""

    def __init__(self, db_path: Path, export_dir: Path):
        self.export_dir = export_dir
        self.con = duckdb.connect(str(db_path))
        for ddl in SCHEMA:
            self.con.execute(ddl)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], root: Path) -> "ReviewStore":
        rev = cfg["review"]
        return cls(root / rev["db_file"], root / rev["export_dir"])

    def __enter__(self) -> "ReviewStore":
        return self

    def __exit__(self, *_exc) -> None:
        self.con.close()

    def record_review(self, run_id: str, row: ReviewRow) -> None:
        """Store the review of a ticker, replacing an earlier one of the same run (a failed ticker is retried)."""
        self.con.execute(
            "INSERT OR REPLACE INTO reviews (run_id, ticker, status, suggestion, source_type, reason_forgotten,"
            " answers, evidence, verified_ratio, needs_attention, sector_comparison, doc_ids, llm_providers,"
            " prompt_version, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                row.ticker,
                row.status,
                row.suggestion,
                row.source_type,
                row.reason_forgotten,
                json.dumps(row.answers, ensure_ascii=False),
                json.dumps(row.evidence, ensure_ascii=False),
                row.verified_ratio,
                row.needs_attention,
                None if row.sector_comparison is None else json.dumps(row.sector_comparison, ensure_ascii=False),
                json.dumps(row.doc_ids),
                json.dumps(row.llm_providers),
                row.prompt_version,
                datetime.datetime.now(),
            ],
        )
        out = self.export_dir / run_id
        out.mkdir(parents=True, exist_ok=True)
        copy = f"COPY (SELECT * FROM reviews WHERE run_id = ?) TO '{out / 'reviews'}.parquet' (FORMAT PARQUET)"
        self.con.execute(copy, [run_id])

    def reviewed(self, run_id: str) -> set[str]:
        """Tickers whose review succeeded; the others are reviewed again."""
        sql = "SELECT ticker FROM reviews WHERE run_id = ? AND status = ?"
        return {t for (t,) in self.con.execute(sql, [run_id, F.ReviewStatus.OK]).fetchall()}

    def reviews(self, run_id: str) -> dict[str, dict[str, Any]]:
        """Ticker -> the run's review (status, answers, evidence, verified_ratio, llm_providers)."""
        sql = "SELECT ticker, status, answers, evidence, verified_ratio, llm_providers FROM reviews WHERE run_id = ?"
        return {
            t: {
                "status": status,
                "answers": json.loads(a),
                "evidence": json.loads(e),
                "verified_ratio": ratio,
                "llm_providers": json.loads(providers),
            }
            for t, status, a, e, ratio, providers in self.con.execute(sql, [run_id]).fetchall()
        }

    def record_eval(self, prompt_version: str, model: str, result: "EvalResult", summary: list[dict[str, Any]]) -> None:
        """Store the outcome of a ``review-eval``; ``summary`` lists the cases with their hit."""
        self.con.execute(
            "INSERT INTO review_evals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                prompt_version,
                model,
                result.passed,
                result.hit_rate,
                result.parse_failures,
                result.min_verified_ratio,
                datetime.datetime.now(),
                json.dumps(summary, ensure_ascii=False),
            ],
        )
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.con.execute(f"COPY review_evals TO '{self.export_dir / 'review_evals'}.parquet' (FORMAT PARQUET)")

    def passed_eval(self, prompt_version: str, model: str) -> bool:
        """Whether the latest ``review-eval`` of this prompt version and model passed."""
        sql = 'SELECT passed FROM review_evals WHERE prompt_version = ? AND model = ? ORDER BY "at" DESC LIMIT 1'
        row = self.con.execute(sql, [prompt_version, model]).fetchone()
        return row is not None and row[0]
