import argparse
import sys
from typing import Any

import pandas as pd
from tqdm import tqdm

from src.cache import StockCache, refresh
from src.config import CFG, ROOT
from src.report import write_report
from src.screener import Screener
from src.tickers import update_ticker_csv
from src.yahoo import YahooClient


def get_japan_tickers() -> list[str]:
    """Tickers from ``system.input_csv`` (".T" appended if missing); exits with status 1 if unusable."""
    csv_path = ROOT / CFG["system"]["input_csv"]

    if not csv_path.exists():
        print(f"Error: ticker CSV not found: {csv_path}")
        sys.exit(1)

    print(f"Reading tickers from {csv_path}...")
    df = pd.read_csv(csv_path)
    col = next((c for c in ["code", "Code", "ticker", "Ticker"] if c in df.columns), None)
    if col is None:
        print(f"Error: {csv_path} needs a 'code', 'Code', 'ticker' or 'Ticker' column.")
        sys.exit(1)

    tickers = []
    for t in df[col].astype(str):
        t = t.strip()
        if not t.endswith(".T"):
            t += ".T"
        tickers.append(t)
    return tickers


def run_fetch(tickers: list[str], cache: StockCache, client: YahooClient):
    print(f"Starting Data Fetch for {len(tickers)} stocks...")
    days = CFG["system"]["cache_days"]
    fetched = sum(refresh(cache, client, t, days) for t in tqdm(tickers))
    print(f"fetched {fetched} / {len(tickers)}")


def run_analyze(tickers: list[str], cache: StockCache, screener: Screener, output_cfg: dict[str, Any]):
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
    write_report(results, ROOT / output_cfg["dir"], output_cfg["filename"], output_cfg["columns"], output_cfg["top_n"])


def main():
    parser = argparse.ArgumentParser(description="Emin Yurumazu Screener")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("fetch", help="Fetch data from Yahoo Finance")

    subparsers.add_parser("analyze", help="Analyze cached data")

    subparsers.add_parser("tickers", help="Update the ticker CSV from the JPX listed company list")

    args = parser.parse_args()

    if args.command == "tickers":
        out_csv = ROOT / CFG["system"]["input_csv"]
        count = update_ticker_csv(out_csv, CFG["tickers"]["jpx_url"], CFG["tickers"]["markets"])
        print(f"Saved {count} tickers to {out_csv}")
        return

    tickers = get_japan_tickers()
    with StockCache(str(ROOT / CFG["system"]["db_file"]), CFG["system"]["market_timezone"]) as cache:
        if args.command == "fetch":
            run_fetch(
                tickers,
                cache,
                YahooClient(
                    CFG["system"]["sleep_time"],
                    CFG["system"]["daily_history_period"],
                    CFG["system"]["monthly_history_period"],
                ),
            )
        elif args.command == "analyze":
            run_analyze(tickers, cache, Screener.from_config(CFG), CFG["output"])
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
