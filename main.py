import argparse
import datetime
import sys
from functools import partial

import pandas as pd
from tqdm import tqdm

from src.cache import StockCache, refresh
from src.config import CFG, ROOT
from src.records import NO_CACHE, RecordStore, evaluate, git_sha
from src.report import write_report
from src.screener import Screener, ScreenResult
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


def run_analyze(tickers: list[str], cache: StockCache, screener: Screener, issue: str | None):
    print(f"Starting Analysis for {len(tickers)} stocks (using cache)...")
    output_cfg, rec = CFG["output"], CFG["records"]
    screened = []
    for ticker in tqdm(tickers):
        data = cache.get(ticker)
        res = screener.screen(data) if data is not None else ScreenResult(False, NO_CACHE, {})
        screened.append(
            {
                "ticker": ticker,
                "stage1_pass": res.passed,
                "stage1_fail_rule": res.fail_rule,
                "improvement_class": res.row.get("Improvement_Class"),
                "metrics": res.row,
            }
        )
    results = [r["metrics"] for r in screened if r["stage1_pass"]]
    no_cache = sum(r["stage1_fail_rule"] == NO_CACHE for r in screened)

    fetched_min, fetched_max = cache.fetched_range()
    info = {
        "issue": issue,
        "git_sha": git_sha(),
        "config": CFG,
        "ticker_list_date": datetime.date.fromtimestamp((ROOT / CFG["system"]["input_csv"]).stat().st_mtime),
        "data_fetched_min": fetched_min,
        "data_fetched_max": fetched_max,
    }
    with RecordStore(ROOT / rec["db_file"], ROOT / rec["export_dir"]) as store:
        print(f"Recorded run {store.record_run(info, screened)} ({len(screened)} tickers).")
    if no_cache:
        print(f"{no_cache} tickers had no cache (run `fetch` first).")
    if not results:
        print("No stocks passed the Gatekeeper.")
        return
    write_report(results, ROOT / output_cfg["dir"], output_cfg["filename"], output_cfg["columns"], output_cfg["top_n"])


# Days of history fetched before the earliest run, so a close "on or before t0" exists across holidays.
LOOKBACK_DAYS = 14


def run_evaluate(client: YahooClient):
    rec = CFG["records"]
    with RecordStore(ROOT / rec["db_file"], ROOT / rec["export_dir"]) as store:
        earliest = min((at for _, at in store.runs()), default=datetime.datetime.now())
        start = (earliest - datetime.timedelta(days=LOOKBACK_DAYS)).date()
        history = partial(client.adjusted_close, start=start)
        added = evaluate(store, history, rec["horizons_months"], rec["benchmark_ticker"], datetime.datetime.now())
    print(f"Added {added} outcome rows.")


def main():
    parser = argparse.ArgumentParser(description="Emin Yurumazu Screener")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("fetch", help="Fetch data from Yahoo Finance")

    analyze = subparsers.add_parser("analyze", help="Analyze cached data and record the run")
    analyze.add_argument("--issue", help="Shikiho issue (YYYY-MM) the ticker research is based on")

    subparsers.add_parser("evaluate", help="Compute outcomes of recorded runs whose horizons have elapsed")

    subparsers.add_parser("tickers", help="Update the ticker CSV from the JPX listed company list")

    args = parser.parse_args()

    if args.command == "tickers":
        out_csv = ROOT / CFG["system"]["input_csv"]
        count = update_ticker_csv(out_csv, CFG["tickers"]["jpx_url"], CFG["tickers"]["markets"])
        print(f"Saved {count} tickers to {out_csv}")
        return

    sc = CFG["system"]
    client = YahooClient(sc["sleep_time"], sc["daily_history_period"], sc["monthly_history_period"])
    if args.command == "evaluate":
        run_evaluate(client)
        return

    tickers = get_japan_tickers()
    with StockCache(str(ROOT / sc["db_file"]), sc["market_timezone"]) as cache:
        if args.command == "fetch":
            run_fetch(tickers, cache, client)
        elif args.command == "analyze":
            run_analyze(tickers, cache, Screener.from_config(CFG), args.issue)
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
