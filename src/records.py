"""Records of screening runs and their later outcomes (a DuckDB file, exported to Parquet per run)."""

import datetime
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import pandas as pd

from . import fields as F
from .screener import NO_CACHE, ScreenResult

if TYPE_CHECKING:  # review_eval imports review, which imports this module
    from .review_eval import EvalResult

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, run_at TIMESTAMP, issue TEXT, git_sha TEXT, config JSON,
        ticker_list_date DATE, data_fetched_min TIMESTAMP, data_fetched_max TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS screen_results (
        run_id TEXT, ticker TEXT, stage1_pass BOOLEAN, stage1_fail_rule TEXT, improvement_class TEXT,
        stage2_candidate BOOLEAN, next_earnings_date DATE, rebuttal_flags JSON, metrics JSON,
        PRIMARY KEY (run_id, ticker))""",
    """CREATE TABLE IF NOT EXISTS outcomes (
        run_id TEXT, ticker TEXT, horizon_months INTEGER, price_t0 DOUBLE, price_t1 DOUBLE, "return" DOUBLE,
        benchmark_return DOUBLE, excess DOUBLE, computed_at TIMESTAMP, PRIMARY KEY (run_id, ticker, horizon_months))""",
    """CREATE TABLE IF NOT EXISTS reviews (
        run_id TEXT, ticker TEXT, status TEXT, suggestion TEXT, source_type TEXT, reason_forgotten TEXT,
        answers JSON, evidence JSON, verified_ratio DOUBLE, needs_attention BOOLEAN, sector_comparison JSON,
        doc_ids JSON, llm_providers JSON, prompt_version TEXT, reviewed_at TIMESTAMP, PRIMARY KEY (run_id, ticker))""",
    """CREATE TABLE IF NOT EXISTS review_evals (
        prompt_version TEXT, model TEXT, passed BOOLEAN, hit_rate DOUBLE, parse_failures INTEGER,
        min_verified_ratio DOUBLE, "at" TIMESTAMP, summary JSON)""",
)


@dataclass(frozen=True)
class RunInfo:
    issue: str | None
    git_sha: str | None
    config: dict[str, Any]
    ticker_list_date: datetime.date
    data_fetched_min: datetime.datetime | None
    data_fetched_max: datetime.datetime | None


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
    doc_ids: list[str]
    llm_providers: list[str]
    prompt_version: str


def latest_issue(today: datetime.date, months: Sequence[int], release_day: int) -> str:
    """Latest Shikiho issue (``YYYY-MM``) out by ``today``; an issue is out on ``release_day`` of its month."""
    released = [
        (year, month)
        for year in (today.year - 1, today.year)
        for month in months
        if datetime.date(year, month, release_day) <= today
    ]
    return "{}-{:02d}".format(*max(released))


def git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


class RecordStore:
    """Run records in ``db_path``; every write is also exported as Parquet to ``export_dir/<run_id>/``.

    Reviews are exported to ``review_export_dir`` instead (they quote web articles and are not committed).
    """

    def __init__(self, db_path: Path, export_dir: Path, review_export_dir: Path):
        self.export_dir = export_dir
        self.review_export_dir = review_export_dir
        self.con = duckdb.connect(str(db_path))
        for ddl in SCHEMA:
            self.con.execute(ddl)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], root: Path) -> "RecordStore":
        rec = cfg["records"]
        return cls(root / rec["db_file"], root / rec["export_dir"], root / cfg["review"]["export_dir"])

    def __enter__(self) -> "RecordStore":
        return self

    def __exit__(self, *_exc) -> None:
        self.con.close()

    def record_run(self, info: RunInfo, results: Mapping[str, ScreenResult]) -> str:
        """Store one run and a row per ticker; ``quality_flags`` is NULL only for tickers without cached data."""
        run_at = datetime.datetime.now()
        run_id = run_at.strftime("%Y%m%dT%H%M%S%f")
        self.con.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                run_at,
                info.issue,
                info.git_sha,
                json.dumps(info.config, default=str),
                info.ticker_list_date,
                info.data_fetched_min,
                info.data_fetched_max,
            ],
        )
        self.con.executemany(
            "INSERT INTO screen_results"
            " (run_id, ticker, stage1_pass, stage1_fail_rule, improvement_class, stage2_candidate,"
            "  next_earnings_date, rebuttal_flags, metrics) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [
                    run_id,
                    ticker,
                    res.passed,
                    res.fail_rule,
                    res.row.get(F.IMPROVEMENT_CLASS),
                    res.row.get(F.STAGE2_CANDIDATE, False),
                    res.row.get(F.NEXT_EARNINGS_DATE),
                    None if res.row.get(F.QUALITY_FLAGS) is None else json.dumps(res.row[F.QUALITY_FLAGS]),
                    pd.Series(res.row, dtype=object).to_json(),
                ]
                for ticker, res in results.items()
            ],
        )
        self._export(self.export_dir, run_id, ["runs", "screen_results"])
        return run_id

    def runs(self) -> list[tuple[str, datetime.datetime]]:
        return self.con.execute("SELECT run_id, run_at FROM runs ORDER BY run_id").fetchall()

    def tickers(self, run_id: str) -> list[str]:
        """Tickers of a run that were screened (without those lacking cached data)."""
        sql = "SELECT ticker FROM screen_results WHERE run_id = ? AND stage1_fail_rule IS DISTINCT FROM ?"
        return [t for (t,) in self.con.execute(sql, [run_id, NO_CACHE]).fetchall()]

    def candidates(self, run_id: str) -> list[tuple[str, dict[str, Any]]]:
        """(ticker, metrics) of the run's stage 2 candidates."""
        sql = "SELECT ticker, metrics FROM screen_results WHERE run_id = ? AND stage2_candidate ORDER BY ticker"
        return [(t, json.loads(m)) for t, m in self.con.execute(sql, [run_id]).fetchall()]

    def has_outcomes(self, run_id: str, horizon_months: int) -> bool:
        sql = "SELECT 1 FROM outcomes WHERE run_id = ? AND horizon_months = ? LIMIT 1"
        return self.con.execute(sql, [run_id, horizon_months]).fetchone() is not None

    def add_outcomes(self, run_id: str, rows: list[list[Any]]) -> None:
        """Insert ``[ticker, horizon_months, price_t0, price_t1, return, benchmark_return, excess]`` rows."""
        now = datetime.datetime.now()
        self.con.executemany(
            "INSERT INTO outcomes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [[run_id, *r, now] for r in rows]
        )
        self._export(self.export_dir, run_id, ["outcomes"])

    def _export(self, root: Path, run_id: str, tables: Sequence[str]) -> None:
        out = root / run_id
        out.mkdir(parents=True, exist_ok=True)
        for table in tables:
            self.con.execute(
                f"COPY (SELECT * FROM {table} WHERE run_id = ?) TO '{out / table}.parquet' (FORMAT PARQUET)", [run_id]
            )

    def record_review(self, run_id: str, row: ReviewRow) -> None:
        """Store the review of a ticker, replacing an earlier one of the same run (a failed ticker is retried)."""
        self.con.execute(
            "INSERT OR REPLACE INTO reviews (run_id, ticker, status, suggestion, source_type, reason_forgotten,"
            " answers, evidence, verified_ratio, needs_attention, doc_ids, llm_providers, prompt_version, reviewed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                json.dumps(row.doc_ids),
                json.dumps(row.llm_providers),
                row.prompt_version,
                datetime.datetime.now(),
            ],
        )
        self._export(self.review_export_dir, run_id, ["reviews"])

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
        self.review_export_dir.mkdir(parents=True, exist_ok=True)
        self.con.execute(f"COPY review_evals TO '{self.review_export_dir / 'review_evals'}.parquet' (FORMAT PARQUET)")

    def passed_eval(self, prompt_version: str, model: str) -> bool:
        """Whether the latest ``review-eval`` of this prompt version and model passed."""
        sql = 'SELECT passed FROM review_evals WHERE prompt_version = ? AND model = ? ORDER BY "at" DESC LIMIT 1'
        row = self.con.execute(sql, [prompt_version, model]).fetchone()
        return row is not None and row[0]


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
