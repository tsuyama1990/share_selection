import duckdb
import yfinance as yf
import pandas as pd
import json
import datetime
import time
import io
from typing import Optional, Dict, Any
from .config import get_system_config

SYS = get_system_config()
DB_FILE = 'stocks_cache.duckdb'

class StockDataManager:
    """
    Manages stock data fetching and caching using DuckDB.
    """
    
    def __init__(self, db_path: str = DB_FILE, expiry_days: Optional[int] = None):
        """
        Initialize the DataManager.

        Parameters
        ----------
        db_path : str, optional
            Path to the DuckDB file, by default DB_FILE.
        expiry_days : int, optional
            Cache expiry in days. If None, uses system config or defaults to 3.
        """
        self.db_path = db_path
        self.expiry_days = expiry_days if expiry_days is not None else SYS.get('cache_days', 3)
        self.con = duckdb.connect(self.db_path)
        self._init_db()
        self.last_req_time = 0.0 # Track last API request time for rate limiting

    def _init_db(self):
        """Initialize the database schema and perform migrations if necessary."""
        # Create table if not exists with new schema
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
        
        # Schema Migration: Add columns if they strictly don't exist
        for col in ['history_monthly', 'cashflow']:
            try:
                self.con.execute(f"ALTER TABLE stock_cache ADD COLUMN {col} JSON")
            except Exception:
                pass # Column likely exists

    def get_data(self, ticker_symbol: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve stock data from cache or API.

        Parameters
        ----------
        ticker_symbol : str
            Ticker symbol (e.g., '7203.T').

        Returns
        -------
        Optional[Dict[str, Any]]
            Dictionary containing stock data or None if fetch failed.
        """
        # 1. Check Cache
        expiry_date = datetime.datetime.now() - datetime.timedelta(days=self.expiry_days)
        
        try:
            res = self.con.execute("""
                SELECT info, fast_info, financials, balance_sheet, history, history_monthly, cashflow
                FROM stock_cache 
                WHERE ticker = ? AND updated_at > ?
            """, [ticker_symbol, expiry_date]).fetchone()
        except duckdb.BinderException:
            res = None

        if res:
            # Cache Hit
            try:
                return {
                    'info': json.loads(res[0]),
                    'fast_info': json.loads(res[1]),
                    'financials': pd.read_json(io.StringIO(res[2])) if res[2] else pd.DataFrame(),
                    'balance_sheet': pd.read_json(io.StringIO(res[3])) if res[3] else pd.DataFrame(),
                    'history': pd.read_json(io.StringIO(res[4])) if res[4] else pd.DataFrame(),
                    'history_monthly': pd.read_json(io.StringIO(res[5])) if res[5] else pd.DataFrame(),
                    'cashflow': pd.read_json(io.StringIO(res[6])) if res[6] else pd.DataFrame()
                }
            except Exception as e:
                print(f"Cache Corrupt for {ticker_symbol}: {e}")
                pass 
        
        # 2. Cache Miss (Fetch from API)
        return self._fetch_from_api(ticker_symbol)

    def _fetch_from_api(self, ticker_symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch data from Yahoo Finance and cache it.

        Parameters
        ----------
        ticker_symbol : str
            Ticker symbol.

        Returns
        -------
        Optional[Dict[str, Any]]
           Fetched data dictionary or None on failure.
        """
        try:
            # Smart Rate Limiting (Adaptive Sleep)
            elapsed = time.time() - self.last_req_time
            required_wait = SYS.get('sleep_time', 0.5)
            sleep_duration = max(0, required_wait - elapsed)
            
            if sleep_duration > 0:
                time.sleep(sleep_duration)
            
            self.last_req_time = time.time()
            
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

            # DataFrames
            fin = ticker.financials
            bs = ticker.balance_sheet
            cf = ticker.cashflow
            hist = ticker.history(period="1y")
            hist_monthly = ticker.history(period="max", interval="1mo")

            # Upsert
            self.con.execute("""
                INSERT OR REPLACE INTO stock_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                ticker_symbol,
                datetime.datetime.now(),
                json.dumps(info_dict),
                json.dumps(fast_info_dict),
                fin.to_json(date_format='iso'),
                bs.to_json(date_format='iso'),
                hist.to_json(date_format='iso'),
                hist_monthly.to_json(date_format='iso'),
                cf.to_json(date_format='iso')
            ])
            
            return {
                'info': info_dict,
                'fast_info': fast_info_dict,
                'financials': fin,
                'balance_sheet': bs,
                'history': hist,
                'history_monthly': hist_monthly,
                'cashflow': cf
            }

        except Exception:
            # print(f"Fetch Error {ticker_symbol}: {e}")
            return None

    def close(self):
        """Close the database connection."""
        self.con.close()
