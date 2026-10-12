import io
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

# Output schema (not a parameter): JPX column -> CSV column
COLUMNS = {
    "コード": "code",
    "銘柄名": "name",
    "市場・商品区分": "market",
    "33業種区分": "sector33",
    "規模区分": "size",
}


def build_ticker_list(xlsx: bytes, markets: Sequence[str]) -> pd.DataFrame:
    """
    Extract domestic common stocks from the JPX listed company workbook.

    Parameters
    ----------
    xlsx : bytes
        Contents of JPX data_j.xlsx.
    markets : Sequence[str]
        Market/product categories to keep (e.g., domestic common stocks only).

    Returns
    -------
    pd.DataFrame
        Columns: code, name, market, sector33, size.
    """
    df = pd.read_excel(io.BytesIO(xlsx), dtype=str)
    df = df[df["市場・商品区分"].isin(markets)]
    return df[list(COLUMNS)].rename(columns=COLUMNS).reset_index(drop=True)


def update_ticker_csv(out_csv: Path, url: str, markets: Sequence[str]) -> int:
    """
    Download the JPX list and write the ticker CSV.

    Parameters
    ----------
    out_csv : Path
        Destination CSV (read later by fetch/analyze).
    url : str
        JPX workbook URL.
    markets : Sequence[str]
        Market/product categories to keep.

    Returns
    -------
    int
        Number of tickers written.
    """
    with urllib.request.urlopen(url, timeout=60) as res:
        tickers = build_ticker_list(res.read(), markets)
    tickers.to_csv(out_csv, index=False, encoding="utf-8")
    return len(tickers)
