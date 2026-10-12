import duckdb
import yfinance as yf
import pandas as pd
import json
import datetime
import time
import io
from pathlib import Path
from typing import Optional, Dict, Any
from .config import CFG, ROOT

SYS = CFG['system']

# DataFrame fields stored as JSON in the cache (order matches the table)
FRAME_KEYS = ('financials', 'balance_sheet', 'history', 'history_monthly', 'cashflow')

class StockDataManager:
    """
    Manages stock data fetching and caching using DuckDB.
    """
    
    def __init__(self, db_path: Optional[str] = None, expiry_days: Optional[int] = None):
        """
        Initialize the DataManager.

        Parameters
        ----------
        db_path : str, optional
            Path to the DuckDB file. If None, uses ``system.db_file`` from
            config (relative paths are resolved against the repo root).
        expiry_days : int, optional
            Cache expiry in days. If None, uses ``system.cache_days`` from config.
        """
        self.db_path = str(ROOT / (db_path or SYS['db_file']))
        self.expiry_days = expiry_days if expiry_days is not None else SYS['cache_days']
        self.con = duckdb.connect(self.db_path)
        self._init_db()

    def _init_db(self):
        """Create the cache table if it does not exist."""
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
                cashflow JSON
            )
        """)

    def get_cached(self, ticker_symbol: str) -> Optional[Dict[str, Any]]:
        """
        Read stock data from the cache regardless of its age. Never hits the API.

        Parameters
        ----------
        ticker_symbol : str
            Ticker symbol (e.g., '7203.T').

        Returns
        -------
        Optional[Dict[str, Any]]
            Dictionary containing stock data, or None if not cached or corrupt.
        """
        res = self.con.execute(f"""
            SELECT info, fast_info, {', '.join(FRAME_KEYS)}
            FROM stock_cache
            WHERE ticker = ?
        """, [ticker_symbol]).fetchone()
        if not res:
            return None

        try:
            data = {'info': json.loads(res[0]), 'fast_info': json.loads(res[1])}
            for key, raw in zip(FRAME_KEYS, res[2:]):
                data[key] = pd.read_json(io.StringIO(raw)) if raw else pd.DataFrame()
            return data
        except Exception as e:
            print(f"Cache Corrupt for {ticker_symbol}: {e}")
            return None

    def _is_fresh(self, ticker_symbol: str) -> bool:
        """
        Check whether the cache entry is younger than ``expiry_days``.

        Parameters
        ----------
        ticker_symbol : str
            Ticker symbol.

        Returns
        -------
        bool
            True if a fresh cache entry exists.
        """
        expiry_date = datetime.datetime.now() - datetime.timedelta(days=self.expiry_days)
        return self.con.execute(
            "SELECT 1 FROM stock_cache WHERE ticker = ? AND updated_at > ?",
            [ticker_symbol, expiry_date]
        ).fetchone() is not None

    def fetch(self, ticker_symbol: str) -> bool:
        """
        Download data from Yahoo Finance and upsert it into the cache.

        Skips the download if the cache is younger than ``expiry_days``.

        Parameters
        ----------
        ticker_symbol : str
            Ticker symbol.

        Returns
        -------
        bool
            True if the cache is up to date (skipped or downloaded),
            False on failure.
        """
        if self._is_fresh(ticker_symbol):
            return True

        try:
            time.sleep(SYS['sleep_time'])
            ticker = yf.Ticker(ticker_symbol)
            
            # fast_info
            try:
                fi = ticker.fast_info
                fast_info_dict = {
                    'market_cap': fi.market_cap,
                    'last_price': fi.last_price
                }
            except Exception:
                fast_info_dict = {}

            # info
            try:
                info_dict = ticker.info
            except Exception:
                info_dict = {}

            frames = {
                'financials': ticker.financials,
                'balance_sheet': ticker.balance_sheet,
                'history': ticker.history(period="1y"),
                'history_monthly': ticker.history(period="max", interval="1mo"),
                'cashflow': ticker.cashflow,
            }

            # Upsert
            self.con.execute(f"""
                INSERT OR REPLACE INTO stock_cache
                (ticker, updated_at, info, fast_info, {', '.join(FRAME_KEYS)})
                VALUES (?, ?, ?, ?, {', '.join('?' for _ in FRAME_KEYS)})
            """, [
                ticker_symbol,
                datetime.datetime.now(),
                json.dumps(info_dict),
                json.dumps(fast_info_dict),
                *(frames[k].to_json(date_format='iso') for k in FRAME_KEYS)
            ])
            return True

        except Exception as e:
            print(f"Fetch failed {ticker_symbol}: {e}")
            return False

    def close(self):
        """Close the database connection."""
        self.con.close()
