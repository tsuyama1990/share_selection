import pandas as pd
import datetime
import os
import sys
import argparse
from tqdm import tqdm
from typing import List
from src.data_manager import StockDataManager
from src.analyzer import analyze_stock_data
from src.config import CFG

def get_japan_tickers() -> List[str]:
    """
    Retrieve the ticker list from the CSV given by ``system.input_csv``.

    Exits with status 1 if the CSV is missing or has no ticker column.

    Returns
    -------
    List[str]
        List of ticker symbols (e.g., ['7203.T', ...]).
    """
    csv_path = CFG['system']['input_csv']
    
    if not os.path.exists(csv_path):
        print(f"Error: ticker CSV not found: {csv_path}")
        sys.exit(1)

    print(f"Reading tickers from {csv_path}...")
    df = pd.read_csv(csv_path)
    col = next((c for c in ['code', 'Code', 'ticker', 'Ticker'] if c in df.columns), None)
    if col is None:
        print(f"Error: {csv_path} needs a 'code', 'Code', 'ticker' or 'Ticker' column.")
        sys.exit(1)

    tickers = []
    for t in df[col].astype(str):
        t = t.strip()
        if not t.endswith('.T'):
            t += '.T'
        tickers.append(t)
    return tickers

def run_fetch(tickers: List[str], dm: StockDataManager):
    """
    Execute data fetching process.

    Parameters
    ----------
    tickers : List[str]
        List of tickers to fetch.
    dm : StockDataManager
        Data manager instance.
    """
    print(f"Starting Data Fetch for {len(tickers)} stocks...")

    fetched = sum(dm.fetch(ticker) for ticker in tqdm(tickers))
    print(f"fetched {fetched} / {len(tickers)}")

def run_analyze(tickers: List[str], dm: StockDataManager):
    """
    Execute analysis process using cached data.

    Parameters
    ----------
    tickers : List[str]
        List of tickers to analyze.
    dm : StockDataManager
        Data manager instance.
    """
    print(f"Starting Analysis for {len(tickers)} stocks (using cache)...")
    results = []
    no_cache = 0
    
    for ticker in tqdm(tickers):
        data = dm.get_cached(ticker)
        if data is None:
            no_cache += 1
            continue
        res = analyze_stock_data(ticker, data)
        if res:
            results.append(res)

    if no_cache:
        print(f"{no_cache} tickers had no cache (run `fetch` first).")
            
    if not results:
        print("No stocks passed the Gatekeeper.")
        return

    # Export
    df_res = pd.DataFrame(results)
    
    # Sort by Total Score
    df_res = df_res.sort_values('Total_Score', ascending=False)
    
    # Select columns to display
    display_cols = [
        'Ticker', 'Name', 'Total_Score', 'Recommendation_Type', 
        'Current_Price', 'PSR', 'PBR', 
        'Cash_to_MarketCap_Ratio', 'Dividend_Yield(%)',
        'Sales_CAGR(%)', 'Sales_Growth_Years', 'Avg_Turnover_60D(M JPY)',
        'Operating_Cash_Flow', 'Investing_Cash_Flow', 'Financing_Cash_Flow',
        'Chart_Trend', 'MA12', 'MA24',
        'Equity_Ratio', 'Operating_Margin(%)'
    ]
    # Ensure cols exist
    existing_cols = [c for c in display_cols if c in df_res.columns]
    
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    csv_name = f"emin_screening_result_{today}.csv"
    df_res[existing_cols].to_csv(csv_name, index=False, encoding='utf-8-sig') # sig for Excel
    
    print(f"\nAnalysis Complete!")
    print(f"Passed: {len(df_res)} stocks")
    print(f"Saved to: {csv_name}")
    print("\nTop 10 Candidates:")
    print(df_res[existing_cols].head(10).to_string(index=False))

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Emin Yurumazu Screener")
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Fetch command
    subparsers.add_parser('fetch', help='Fetch data from Yahoo Finance')
    
    # Analyze command
    subparsers.add_parser('analyze', help='Analyze cached data')
    
    args = parser.parse_args()
    
    dm = StockDataManager()
    tickers = get_japan_tickers()

    try:
        if args.command == 'fetch':
            run_fetch(tickers, dm)
        elif args.command == 'analyze':
            run_analyze(tickers, dm)
        else:
            parser.print_help()
    finally:
        dm.close()

if __name__ == "__main__":
    main()
