import io
from collections.abc import Sequence
from pathlib import Path

import httpx
import pandas as pd

# Yahoo Finance suffix of Tokyo Stock Exchange tickers: ticker = code + suffix ("130A" -> "130A.T")
TICKER_SUFFIX = ".T"
# Output schema (not a parameter): JPX column -> CSV column
COLUMNS = {
    "コード": "code",
    "銘柄名": "name",
    "市場・商品区分": "market",
    "33業種区分": "sector33",
    "規模区分": "size",
}


def build_ticker_list(xlsx: bytes, markets: Sequence[str]) -> pd.DataFrame:
    """Rows of the JPX workbook (data_j.xlsx bytes) in ``markets``, with the ``COLUMNS`` renamed."""
    df = pd.read_excel(io.BytesIO(xlsx), dtype=str)
    df = df[df["市場・商品区分"].isin(markets)]
    return df[list(COLUMNS)].rename(columns=COLUMNS).reset_index(drop=True)


def update_ticker_csv(out_csv: Path, url: str, markets: Sequence[str], timeout_s: float) -> int:
    """Download the JPX list, write the ticker CSV, return the number of tickers."""
    res = httpx.get(url, timeout=timeout_s, follow_redirects=True)
    res.raise_for_status()
    tickers = build_ticker_list(res.content, markets)
    tickers.to_csv(out_csv, index=False, encoding="utf-8")
    return len(tickers)


def read_names(csv_path: Path) -> dict[str, str]:
    """Japanese name by ticker from the ``code`` and ``name`` columns of the ticker CSV."""
    df = pd.read_csv(csv_path, dtype=str)
    return {code.strip() + TICKER_SUFFIX: name for code, name in zip(df["code"], df["name"], strict=True)}


def read_tickers(csv_path: Path) -> list[str]:
    """Tickers (code + suffix) from the ``code`` column of the ticker CSV."""
    return [code.strip() + TICKER_SUFFIX for code in pd.read_csv(csv_path, dtype=str)["code"]]
