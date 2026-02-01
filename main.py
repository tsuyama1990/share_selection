import pandas as pd
import datetime
import os
import argparse
from tqdm import tqdm
from typing import List
from src.data_manager import StockDataManager
from src.analyzer import analyze_stock_data
from src.config import get_system_config

def get_japan_tickers() -> List[str]:
    """
    Retrieve ticker list from CSV or use a default demo list.

    Returns
    -------
    List[str]
        List of ticker symbols (e.g., ['7203.T', ...]).
    """
    sys_conf = get_system_config()
    csv_path = sys_conf.get('input_csv', 'japan_tickers.csv')
    
    if os.path.exists(csv_path):
        print(f"Reading tickers from {csv_path}...")
        try:
            df = pd.read_csv(csv_path)
            tickers = []
            # Support various column names
            col = next((c for c in ['code', 'Code', 'ticker', 'Ticker', 'Symbol'] if c in df.columns), None)
            
            if col:
                for t in df[col].astype(str):
                    t = t.strip()
                    if not t.endswith('.T'):
                        t += '.T'
                    tickers.append(t)
                return tickers
        except Exception as e:
            print(f"Error reading CSV: {e}")
            pass
            
    # Fallback / Demo
    print("Using demo ticker list (CSV not found or invalid).")
    return ['7203.T', '6758.T', '9984.T', '8306.T', '6098.T']

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
    
    # Random shuffle to avoid hitting same server nodes consecutively (superstition, but good practice)
    # import random
    # random.shuffle(tickers)

    for ticker in tqdm(tickers):
        dm.get_data(ticker)

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
    
    for ticker in tqdm(tickers):
        data = dm.get_data(ticker)
        res = analyze_stock_data(ticker, data)
        if res:
            results.append(res)
            
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
        'Sales_Growth_4Y(%)',
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
