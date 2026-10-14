"""Records of screening runs and their later outcomes (a DuckDB file, exported to Parquet per run)."""

import datetime
import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY, run_at TIMESTAMP, issue TEXT, git_sha TEXT, config JSON,
        ticker_list_date DATE, data_fetched_min TIMESTAMP, data_fetched_max TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS screen_results (
        run_id TEXT, ticker TEXT, stage1_pass BOOLEAN, stage1_fail_rule TEXT, improvement_class TEXT,
        types JSON, next_earnings_date DATE, rebuttal_flags JSON, metrics JSON, PRIMARY KEY (run_id, ticker))""",
    """CREATE TABLE IF NOT EXISTS outcomes (
        run_id TEXT, ticker TEXT, horizon_months INTEGER, price_t0 DOUBLE, price_t1 DOUBLE, "return" DOUBLE,
        benchmark_return DOUBLE, excess DOUBLE, computed_at TIMESTAMP, PRIMARY KEY (run_id, ticker, horizon_months))""",
)
NO_CACHE = "no_cache"


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

    def __enter__(self) -> "RecordStore":
        return self

    def __exit__(self, *_exc) -> None:
        self.con.close()

    def record_run(self, info: dict[str, Any], results: list[dict[str, Any]]) -> str:
        """Store one run (``info``: issue, git_sha, config, ticker_list_date, data_fetched_min/max) and its ticker rows.

        Each result has ``ticker``, ``stage1_pass``, ``stage1_fail_rule``, ``improvement_class``,
        ``next_earnings_date`` (``YYYY-MM-DD`` or None), ``quality_flags`` (list or None), ``metrics`` (dict).
        """
        run_at = datetime.datetime.now()
        run_id = run_at.strftime("%Y%m%dT%H%M%S%f")
        self.con.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                run_at,
                info["issue"],
                info["git_sha"],
                json.dumps(info["config"], default=str),
                info["ticker_list_date"],
                info["data_fetched_min"],
                info["data_fetched_max"],
            ],
        )
        self.con.executemany(
            "INSERT INTO screen_results"
            " (run_id, ticker, stage1_pass, stage1_fail_rule, improvement_class, next_earnings_date,"
            "  rebuttal_flags, metrics) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [
                    run_id,
                    r["ticker"],
                    r["stage1_pass"],
                    r["stage1_fail_rule"],
                    r["improvement_class"],
                    r["next_earnings_date"],
                    None if r["quality_flags"] is None else json.dumps(r["quality_flags"]),
                    pd.Series(r["metrics"], dtype=object).to_json(),
                ]
                for r in results
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
