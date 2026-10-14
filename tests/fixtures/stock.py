"""StockData built the way the cache builds it (market timezone from the config)."""

from typing import Any

from src.stock_data import StockData
from tests.fixtures.config import CFG


def make_stock(ticker: str, d: dict[str, Any]) -> StockData:
    return StockData.from_dict(ticker, d, CFG["system"]["market_timezone"])
