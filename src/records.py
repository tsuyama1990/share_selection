"""Records of screening runs, their per-ticker results and later outcomes (a DuckDB file, Parquet per run)."""

import datetime
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from . import fields as F
from .screener import NO_CACHE, ScreenResult

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
)


@dataclass(frozen=True)
class RunInfo:
    issue: str | None
    git_sha: str | None
    config: dict[str, Any]
    ticker_list_date: datetime.date
    data_fetched_min: datetime.datetime | None
    data_fetched_max: datetime.datetime | None


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
    """Run records in ``db_path``; every write is also exported as Parquet to ``export_dir/<run_id>/``."""

    def __init__(self, db_path: Path, export_dir: Path):
        self.export_dir = export_dir
        self.con = duckdb.connect(str(db_path))
        for ddl in SCHEMA:
            self.con.execute(ddl)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], root: Path) -> "RecordStore":
        rec = cfg["records"]
        return cls(root / rec["db_file"], root / rec["export_dir"])

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
        self._export(run_id, ["runs", "screen_results"])
        return run_id

    def runs(self) -> list[tuple[str, datetime.datetime]]:
        return self.con.execute("SELECT run_id, run_at FROM runs ORDER BY run_id").fetchall()

    def tickers(self, run_id: str) -> list[str]:
        """Tickers of a run that were screened (without those lacking cached data)."""
        sql = "SELECT ticker FROM screen_results WHERE run_id = ? AND stage1_fail_rule IS DISTINCT FROM ?"
        return [t for (t,) in self.con.execute(sql, [run_id, NO_CACHE]).fetchall()]

    def resolve_run(self, run_id: str | None) -> str:
        """``run_id`` as given, else the latest run's (an error that says what to run when there is none)."""
        if run_id:
            return run_id
        if not (runs := self.runs()):
            raise ValueError("no run is recorded; run `analyze` first")
        return runs[-1][0]

    def candidates(self, run_id: str) -> list[tuple[str, dict[str, Any]]]:
        """(ticker, metrics) of the run's stage 2 candidates, best ``Priority_Rank`` first."""
        sql = "SELECT ticker, metrics FROM screen_results WHERE run_id = ? AND stage2_candidate ORDER BY ticker"
        rows = [(t, json.loads(m)) for t, m in self.con.execute(sql, [run_id]).fetchall()]
        return sorted(rows, key=lambda c: c[1][F.PRIORITY_RANK])

    def run_metrics(self, run_id: str) -> dict[str, dict[str, Any]]:
        """Ticker -> metrics of every ticker of the run that has metrics (the sector medians' population)."""
        sql = "SELECT ticker, metrics FROM screen_results WHERE run_id = ? AND metrics IS NOT NULL"
        return {t: json.loads(m) for t, m in self.con.execute(sql, [run_id]).fetchall()}

    def screen_row(self, run_id: str, ticker: str) -> dict[str, Any]:
        """One ``screen_results`` row: the flags plus the flattened metrics JSON; empty when the ticker has no row."""
        sql = "SELECT stage1_pass, stage1_fail_rule, metrics FROM screen_results WHERE run_id = ? AND ticker = ?"
        row = self.con.execute(sql, [run_id, ticker]).fetchone()
        if row is None:
            return {}
        passed, fail_rule, metrics = row
        return {"stage1_pass": passed, "stage1_fail_rule": fail_rule, **(json.loads(metrics) if metrics else {})}

    def has_outcomes(self, run_id: str, horizon_months: int) -> bool:
        sql = "SELECT 1 FROM outcomes WHERE run_id = ? AND horizon_months = ? LIMIT 1"
        return self.con.execute(sql, [run_id, horizon_months]).fetchone() is not None

    def add_outcomes(self, run_id: str, rows: list[list[Any]]) -> None:
        """Insert ``[ticker, horizon_months, price_t0, price_t1, return, benchmark_return, excess]`` rows."""
        now = datetime.datetime.now()
        self.con.executemany(
            "INSERT INTO outcomes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [[run_id, *r, now] for r in rows]
        )
        self._export(run_id, ["outcomes"])

    def _export(self, run_id: str, tables: Sequence[str]) -> None:
        out = self.export_dir / run_id
        out.mkdir(parents=True, exist_ok=True)
        for table in tables:
            self.con.execute(
                f"COPY (SELECT * FROM {table} WHERE run_id = ?) TO '{out / table}.parquet' (FORMAT PARQUET)", [run_id]
            )
