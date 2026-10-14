import io
import urllib.request
from collections.abc import Sequence
from pathlib import Path

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
    with urllib.request.urlopen(url, timeout=timeout_s) as res:
        tickers = build_ticker_list(res.read(), markets)
    tickers.to_csv(out_csv, index=False, encoding="utf-8")
    return len(tickers)
