import argparse
import datetime
import os
import sys
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

from src.cache import StockCache, refresh
from src.config import CONFIG_FILE, ROOT, load_config
from src.docstore import DocStore
from src.earnings_calendar import load_calendar, update_calendar_csv
from src.edinet import EdinetClient, fetch_annual_report, update_index
from src.llm import GeminiSearch, LLMClient, Provider, RateLimiter
from src.records import NO_CACHE, RecordStore, evaluate, git_sha, latest_issue
from src.report import prioritize, write_report
from src.screener import Screener, ScreenResult
from src.tickers import update_ticker_csv
from src.yahoo import YahooClient


def get_japan_tickers(cfg: dict[str, Any]) -> list[str]:
    """Tickers from ``system.input_csv`` (".T" appended if missing); exits with status 1 if unusable."""
    csv_path = ROOT / cfg["system"]["input_csv"]

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


def run_fetch(cfg: dict[str, Any], tickers: list[str], cache: StockCache, client: YahooClient):
    print(f"Starting Data Fetch for {len(tickers)} stocks...")
    days = cfg["system"]["cache_days"]
    errors = {t: refresh(cache, client, t, days) for t in tqdm(tickers)}
    failures = pd.DataFrame([(t, e) for t, e in errors.items() if e is not None], columns=["ticker", "error"])
    print(f"fetched {len(tickers) - len(failures)} / {len(tickers)}")
    if failures.empty:
        return
    output_cfg = cfg["output"]
    path = ROOT / output_cfg["dir"] / output_cfg["failures_filename"].format(date=datetime.date.today())
    path.parent.mkdir(parents=True, exist_ok=True)
    failures.to_csv(path, index=False, encoding="utf-8")
    print(f"{len(failures)} fetch failures saved to {path}")


def run_analyze(cfg: dict[str, Any], tickers: list[str], cache: StockCache, screener: Screener, issue: str | None):
    print(f"Starting Analysis for {len(tickers)} stocks (using cache)...")
    output_cfg, rec = cfg["output"], cfg["records"]
    calendar = load_calendar(ROOT / cfg["calendar"]["out_csv"])
    screened = []
    for ticker in tqdm(tickers):
        data = cache.get(ticker)
        res = screener.screen(data) if data is not None else ScreenResult(False, NO_CACHE, {})
        next_date, period = calendar.get(ticker, (None, None))
        res.row["Next_Earnings_Date"], res.row["Earnings_Period"] = next_date, period
        flags = res.row.get("Quality_Flags")
        screened.append(
            {
                "ticker": ticker,
                "stage1_pass": res.passed,
                "stage1_fail_rule": res.fail_rule,
                "improvement_class": res.row.get("Improvement_Class"),
                "next_earnings_date": next_date,
                "quality_flags": None if flags is None else [f for f in flags.split(",") if f],
                "metrics": res.row,
            }
        )
    results = [r["metrics"] for r in screened if r["stage1_pass"]]
    prioritize(results, cfg["selection"]["candidates_n"])
    no_cache = sum(r["stage1_fail_rule"] == NO_CACHE for r in screened)

    fetched_min, fetched_max = cache.fetched_range()
    info = {
        "issue": issue,
        "git_sha": git_sha(),
        "config": cfg,
        "ticker_list_date": datetime.date.fromtimestamp((ROOT / cfg["system"]["input_csv"]).stat().st_mtime),
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
    write_report(results, ROOT / output_cfg["dir"], output_cfg["filename"], output_cfg["columns"])


# Days of history fetched before the earliest run, so a close "on or before t0" exists across holidays.
LOOKBACK_DAYS = 14


def run_evaluate(cfg: dict[str, Any], client: YahooClient):
    rec = cfg["records"]
    with RecordStore(ROOT / rec["db_file"], ROOT / rec["export_dir"]) as store:
        earliest = min((at for _, at in store.runs()), default=datetime.datetime.now())
        start = (earliest - datetime.timedelta(days=LOOKBACK_DAYS)).date()
        history = partial(client.adjusted_close, start=start)
        added = evaluate(store, history, rec["horizons_months"], rec["benchmark_ticker"], datetime.datetime.now())
    print(f"Added {added} outcome rows.")


def run_docs(cfg: dict[str, Any], run_id: str | None):
    key = os.environ.get(cfg["edinet"]["key_env"], "")
    if not key:
        print(f"Error: set {cfg['edinet']['key_env']} (environment or .env).")
        sys.exit(1)
    rec = cfg["records"]
    with RecordStore(ROOT / rec["db_file"], ROOT / rec["export_dir"]) as records:
        run_id = run_id or records.runs()[-1][0]
        tickers = [t for t, _ in records.candidates(run_id)]
    print(f"Collecting documents of {len(tickers)} candidates of run {run_id}...")
    with (
        httpx.Client(timeout=cfg["edinet"]["timeout_s"]) as http,
        DocStore(ROOT / cfg["docstore"]["db_file"]) as store,
    ):
        limiter = RateLimiter(1, cfg["edinet"]["request_interval_s"])
        client = EdinetClient(cfg["edinet"]["base_url"], key, http, limiter)
        update_index(client, store, datetime.date.today(), cfg["edinet"]["index_days"])
        stored = [
            fetch_annual_report(client, store, t, cfg["edinet"]["doc_type_code"], cfg["edinet"]["sections"])
            for t in tqdm(tickers)
        ]
    failed = sum(not ids for ids in stored)
    print(f"{sum(map(len, stored))} documents stored for {len(tickers) - failed} tickers; {failed} tickers failed.")


SECONDS_PER_MINUTE = 60
CHECK_CHAT_PROMPT = "Reply with the single word: ok"
CHECK_SEARCH_PROMPT = "What is the Tokyo Stock Exchange's Prime Market? Answer in one sentence."


def run_llm_check(cfg: dict[str, Any]):
    """Smoke test: one prompt through the fallback chain and one grounded search; prints no secrets."""
    llm = cfg["llm"]
    providers = [
        Provider(p["name"], p["base_url"], p["model"], os.environ.get(p["key_env"], "")) for p in llm["providers"]
    ]
    search = llm["search"]
    with httpx.Client(timeout=llm["timeout_s"]) as http:
        limiter = RateLimiter(llm["max_calls_per_minute"], SECONDS_PER_MINUTE)
        reply = LLMClient(providers, http, llm["temperature"], limiter).chat(
            [{"role": "user", "content": CHECK_CHAT_PROMPT}]
        )
        print(f"chat: {reply.provider} / {reply.model}, answer {len(reply.text)} chars")
        key = os.environ.get(search["key_env"], "")
        answer = GeminiSearch(search["base_url"], search["model"], key, http).search(CHECK_SEARCH_PROMPT)
        print(f"search: answer {len(answer.text)} chars, {len(answer.sources)} sources, {len(answer.queries)} queries")


def default_issue(cfg: dict[str, Any]) -> str:
    rec = cfg["records"]
    return latest_issue(datetime.date.today(), rec["shikiho_issue_months"], rec["shikiho_release_day"])


def main():
    parser = argparse.ArgumentParser(description="Emin Yurumazu Screener")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE, help="Config file (default: config.yaml)")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("fetch", help="Fetch data from Yahoo Finance")

    analyze = subparsers.add_parser("analyze", help="Analyze cached data and record the run")
    analyze.add_argument(
        "--issue", help="Shikiho issue (YYYY-MM) the ticker research is based on (default: latest released)"
    )

    subparsers.add_parser("evaluate", help="Compute outcomes of recorded runs whose horizons have elapsed")

    subparsers.add_parser("tickers", help="Update the ticker CSV from the JPX listed company list")

    subparsers.add_parser("calendar", help="Update the earnings calendar CSV from the JPX announcement schedule")

    docs = subparsers.add_parser("docs", help="Collect EDINET annual report sections of a run's stage 2 candidates")
    docs.add_argument("--run", help="Run id (default: the latest run)")

    subparsers.add_parser("llm-check", help="Smoke-test the LLM fallback chain and Gemini search")

    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config(args.config)

    if args.command == "llm-check":
        run_llm_check(cfg)
        return

    if args.command == "docs":
        run_docs(cfg, args.run)
        return

    if args.command == "tickers":
        out_csv = ROOT / cfg["system"]["input_csv"]
        count = update_ticker_csv(out_csv, cfg["tickers"]["jpx_url"], cfg["tickers"]["markets"])
        print(f"Saved {count} tickers to {out_csv}")
        return

    if args.command == "calendar":
        out_csv = ROOT / cfg["calendar"]["out_csv"]
        count = update_calendar_csv(
            out_csv, cfg["calendar"]["page_url"], cfg["calendar"]["link_pattern"], cfg["calendar"]["user_agent"]
        )
        print(f"Saved {count} announcement dates to {out_csv}")
        return

    sc = cfg["system"]
    client = YahooClient(sc["sleep_time"], sc["daily_history_period"], sc["monthly_history_period"])
    if args.command == "evaluate":
        run_evaluate(cfg, client)
        return

    tickers = get_japan_tickers(cfg)
    with StockCache(str(ROOT / sc["db_file"]), sc["market_timezone"]) as cache:
        if args.command == "fetch":
            run_fetch(cfg, tickers, cache, client)
        elif args.command == "analyze":
            run_analyze(cfg, tickers, cache, Screener.from_config(cfg), args.issue or default_issue(cfg))
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
