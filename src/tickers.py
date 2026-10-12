import io
import urllib.request
from pathlib import Path

import pandas as pd

# JPX "東証上場銘柄一覧" (updated monthly)
JPX_LIST_URL = 'https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx'

# Domestic common stocks only (excludes ETF/REIT/PRO Market/foreign stocks)
MARKETS = ('プライム（内国株式）', 'スタンダード（内国株式）', 'グロース（内国株式）')

COLUMNS = {
    'コード': 'code',
    '銘柄名': 'name',
    '市場・商品区分': 'market',
    '33業種区分': 'sector33',
    '規模区分': 'size',
}

def build_ticker_list(xlsx: bytes) -> pd.DataFrame:
    """
    Extract domestic common stocks from the JPX listed company workbook.

    Parameters
    ----------
    xlsx : bytes
        Contents of JPX data_j.xlsx.

    Returns
    -------
    pd.DataFrame
        Columns: code, name, market, sector33, size.
    """
    df = pd.read_excel(io.BytesIO(xlsx), dtype=str)
    df = df[df['市場・商品区分'].isin(MARKETS)]
    return df[list(COLUMNS)].rename(columns=COLUMNS).reset_index(drop=True)

def update_ticker_csv(out_csv: Path, url: str = JPX_LIST_URL) -> int:
    """
    Download the JPX list and write the ticker CSV.

    Parameters
    ----------
    out_csv : Path
        Destination CSV (read later by fetch/analyze).
    url : str, optional
        JPX workbook URL, by default JPX_LIST_URL.

    Returns
    -------
    int
        Number of tickers written.
    """
    with urllib.request.urlopen(url, timeout=60) as res:
        tickers = build_ticker_list(res.read())
    tickers.to_csv(out_csv, index=False, encoding='utf-8')
    return len(tickers)
