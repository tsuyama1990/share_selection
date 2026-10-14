"""DuckDB cache of raw stock data."""

import datetime
import io
import json
from typing import Any

import duckdb
import pandas as pd

from .stock_data import StockData

FRAME_KEYS = ("financials", "balance_sheet", "history", "history_monthly", "cashflow", "quarterly_income")
HISTORY_KEYS = ("history", "history_monthly")


class StockCache:
    """Persists raw stock data in a DuckDB file. Usable as a context manager."""

    def __init__(self, db_path: str, market_timezone: str):
        self.market_timezone = market_timezone
        self.con = duckdb.connect(str(db_path))
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS stock_cache (
                ticker TEXT PRIMARY KEY,
                updated_at TIMESTAMP,
                info JSON,
                fast_info JSON,
                financials JSON,
                balance_sheet JSON,
                history JSON,
                history_monthly JSON,
                cashflow JSON,
                quarterly_income JSON
            )
        """)

    def __enter__(self) -> "StockCache":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def get(self, ticker: str) -> StockData | None:
        """Read a ticker regardless of its age; None if not cached or corrupt."""
        res = self.con.execute(
            f"""
            SELECT info, fast_info, {", ".join(FRAME_KEYS)}
            FROM stock_cache WHERE ticker = ?
        """,
            [ticker],
        ).fetchone()
        if not res:
            return None
        try:
            d: dict[str, Any] = {"info": json.loads(res[0]), "fast_info": json.loads(res[1])}
            for key, raw in zip(FRAME_KEYS, res[2:], strict=True):
                df = pd.read_json(io.StringIO(raw)) if raw else pd.DataFrame()
                if key in HISTORY_KEYS and not df.empty:
                    # JSON holds UTC instants (to_json converts tz-aware indexes to UTC)
                    df.index = pd.to_datetime(df.index, utc=True)
                d[key] = df
            return StockData.from_dict(ticker, d, self.market_timezone)
        except (ValueError, TypeError) as e:
            print(f"Cache Corrupt for {ticker}: {e}")
            return None

    def put(self, ticker: str, raw: dict[str, Any]) -> None:
        """Upsert the dict returned by ``YahooClient.download``."""
        frames: list[pd.DataFrame] = [raw[k] if raw.get(k) is not None else pd.DataFrame() for k in FRAME_KEYS]
        self.con.execute(
            f"""
            INSERT OR REPLACE INTO stock_cache
            (ticker, updated_at, info, fast_info, {", ".join(FRAME_KEYS)})
            VALUES (?, ?, ?, ?, {", ".join("?" for _ in FRAME_KEYS)})
        """,
            [
                ticker,
                datetime.datetime.now(),
                json.dumps(raw.get("info") or {}),
                json.dumps(raw.get("fast_info") or {}),
                *(f.to_json(date_format="iso") for f in frames),
            ],
        )

    def is_fresh(self, ticker: str, max_age_days: float) -> bool:
        limit = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
        return (
            self.con.execute(
                "SELECT 1 FROM stock_cache WHERE ticker = ? AND updated_at > ?",
                [ticker, limit],
            ).fetchone()
            is not None
        )

    def fetched_range(self) -> tuple[datetime.datetime | None, datetime.datetime | None]:
        """Oldest and newest ``updated_at`` in the cache."""
        return self.con.execute("SELECT min(updated_at), max(updated_at) FROM stock_cache").fetchall()[0]

    def close(self) -> None:
        self.con.close()


def refresh(cache: StockCache, client, ticker: str, max_age_days: float) -> str | None:
    """Download unless a fresh entry exists; None if the cache is up to date afterwards, else the error message."""
    if cache.is_fresh(ticker, max_age_days):
        return None
    try:
        cache.put(ticker, client.download(ticker))
        return None
    except Exception as e:
        return str(e)
