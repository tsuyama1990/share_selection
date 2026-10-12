"""CSV report and console summary of screening results."""
import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

DISPLAY_COLUMNS = [
    'Ticker', 'Name', 'Total_Score', 'Recommendation_Type',
    'Current_Price', 'PSR', 'PBR',
    'NCAV_to_MarketCap_Ratio', 'Dividend_Yield(%)',
    'Sales_CAGR(%)', 'Sales_Growth_Years', 'Avg_Turnover_60D(M JPY)',
    'Operating_Cash_Flow', 'Investing_Cash_Flow', 'Financing_Cash_Flow',
    'Chart_Trend', 'MA12', 'MA24',
    'Equity_Ratio', 'Operating_Margin(%)'
]


def write_report(results: List[Dict[str, Any]], out_dir: str = '.') -> Path:
    """
    Save results to a dated CSV (sorted by Total_Score) and print the top 10.

    Parameters
    ----------
    results : List[Dict[str, Any]]
        Result rows from ``Screener.evaluate`` (must not be empty).
    out_dir : str, optional
        Output directory, by default the current directory.

    Returns
    -------
    Path
        Path of the written CSV.
    """
    df = pd.DataFrame(results).sort_values('Total_Score', ascending=False)
    df = df[[c for c in DISPLAY_COLUMNS if c in df.columns]]

    today = datetime.datetime.now().strftime('%Y-%m-%d')
    path = Path(out_dir) / f"emin_screening_result_{today}.csv"
    df.to_csv(path, index=False, encoding='utf-8-sig')  # sig for Excel

    print("\nAnalysis Complete!")
    print(f"Passed: {len(df)} stocks")
    print(f"Saved to: {path}")
    print("\nTop 10 Candidates:")
    print(df.head(10).to_string(index=False))
    return path
