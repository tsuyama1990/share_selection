import pandas as pd
import os
import sys
import argparse
from tqdm import tqdm
from typing import Any, Dict, List
from src.cache import StockCache, refresh
from src.config import CFG, ROOT
from src.report import write_report
from src.screener import Screener
from src.tickers import update_ticker_csv
from src.yahoo import YahooClient

def get_japan_tickers() -> List[str]:
    """
    Retrieve the ticker list from the CSV given by ``system.input_csv``.

    Exits with status 1 if the CSV is missing or has no ticker column.

    Returns
    -------
    List[str]
        List of ticker symbols (e.g., ['7203.T', ...]).
    """
    csv_path = ROOT / CFG['system']['input_csv']
    
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

def run_fetch(tickers: List[str], cache: StockCache, client: YahooClient):
    """
    Download data for all tickers into the cache.

    Parameters
    ----------
    tickers : List[str]
        List of tickers to fetch.
    cache : StockCache
        Destination cache.
    client : YahooClient
        Yahoo Finance client.
    """
    print(f"Starting Data Fetch for {len(tickers)} stocks...")
    days = CFG['system']['cache_days']
    fetched = sum(refresh(cache, client, t, days) for t in tqdm(tickers))
    print(f"fetched {fetched} / {len(tickers)}")

def run_analyze(tickers: List[str], cache: StockCache, screener: Screener, output_cfg: Dict[str, Any]):
    """
    Screen cached data and write the report.

    Parameters
    ----------
    tickers : List[str]
        List of tickers to analyze.
    cache : StockCache
        Source cache.
    screener : Screener
        Configured screener.
    output_cfg : Dict[str, Any]
        The 'output' config section (dir, filename, top_n, columns).
    """
    print(f"Starting Analysis for {len(tickers)} stocks (using cache)...")
    results = []
    no_cache = 0

    for ticker in tqdm(tickers):
        data = cache.get(ticker)
        if data is None:
            no_cache += 1
            continue
        res = screener.evaluate(data)
        if res:
            results.append(res)

    if no_cache:
        print(f"{no_cache} tickers had no cache (run `fetch` first).")
    if not results:
        print("No stocks passed the Gatekeeper.")
        return
    write_report(results, ROOT / output_cfg['dir'], output_cfg['filename'],
                 output_cfg['columns'], output_cfg['top_n'])

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Emin Yurumazu Screener")
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Fetch command
    subparsers.add_parser('fetch', help='Fetch data from Yahoo Finance')
    
    # Analyze command
    subparsers.add_parser('analyze', help='Analyze cached data')

    # Tickers command
    subparsers.add_parser('tickers', help='Update the ticker CSV from the JPX listed company list')
    
    args = parser.parse_args()

    if args.command == 'tickers':
        out_csv = ROOT / CFG['system']['input_csv']
        print(f"Saved {update_ticker_csv(out_csv, CFG['tickers']['jpx_url'], CFG['tickers']['markets'])} tickers to {out_csv}")
        return
    
    tickers = get_japan_tickers()
    with StockCache(str(ROOT / CFG['system']['db_file'])) as cache:
        if args.command == 'fetch':
            run_fetch(tickers, cache, YahooClient(CFG['system']['sleep_time'], CFG['system']['daily_history_period'],
                                            CFG['system']['monthly_history_period']))
        elif args.command == 'analyze':
            run_analyze(tickers, cache, Screener.from_config(CFG), CFG['output'])
        else:
            parser.print_help()

if __name__ == "__main__":
    main()
