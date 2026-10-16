import argparse
import datetime
import os
import subprocess
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

from src import fields as F
from src.cache import StockCache, refresh
from src.config import CONFIG_FILE, ROOT, load_config
from src.docstore import DocStore
from src.earnings_calendar import load_calendar, update_calendar_csv
from src.edinet import EdinetClient, fetch_annual_report, update_index
from src.llm import GeminiSearch, LLMClient, LLMError, Provider, QuotaExceeded
from src.records import NO_CACHE, RecordStore, evaluate
from src.report import write_report
from src.screener import Screener, ScreenResult
from src.selection import prioritize
from src.throttle import RateLimiter
from src.tickers import TICKER_SUFFIX, read_tickers, update_ticker_csv
from src.webfetch import fetch_document
from src.yahoo import YahooClient

SECONDS_PER_MINUTE = 60


def get_japan_tickers(cfg: dict[str, Any]) -> list[str]:
    """Tickers of ``system.input_csv``; exits with status 1 if the file is missing."""
    csv_path = ROOT / cfg["system"]["input_csv"]
    if not csv_path.exists():
        print(f"Error: ticker CSV not found: {csv_path} (run `tickers`)")
        sys.exit(1)
    print(f"Reading tickers from {csv_path}...")
    return read_tickers(csv_path)


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
        res.row[F.NEXT_EARNINGS_DATE], res.row[F.EARNINGS_PERIOD] = next_date, period
        screened.append(
            {
                "ticker": ticker,
                "stage1_pass": res.passed,
                "stage1_fail_rule": res.fail_rule,
                "improvement_class": res.row.get(F.IMPROVEMENT_CLASS),
                "next_earnings_date": next_date,
                "quality_flags": res.row.get(F.QUALITY_FLAGS),
                "metrics": res.row,
            }
        )
    results = [r["metrics"] for r in screened if r["stage1_pass"]]
    prioritize(results, cfg["selection"]["candidates_n"])
    for r in screened:
        r["stage2_candidate"] = r["metrics"].get(F.STAGE2_CANDIDATE, False)
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


def run_evaluate(cfg: dict[str, Any], client: YahooClient):
    rec = cfg["records"]
    with RecordStore(ROOT / rec["db_file"], ROOT / rec["export_dir"]) as store:
        earliest = min((at for _, at in store.runs()), default=datetime.datetime.now())
        start = (earliest - datetime.timedelta(days=rec["price_lookback_days"])).date()
        history = partial(client.adjusted_close, start=start)
        added = evaluate(store, history, rec["horizons_months"], rec["benchmark_ticker"], datetime.datetime.now())
    print(f"Added {added} outcome rows.")


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(f"Error: set {name} (environment or .env).")
        sys.exit(1)
    return value


def collect_web_documents(cfg: dict[str, Any], search_key: str, candidates: list[tuple[str, dict]], store: DocStore):
    """Gemini search per candidate without web documents (best Priority_Rank first), then fetch its first
    ``docs.max_sources`` sources; stops at the search quota. Returns the documents stored."""
    llm, search, web, docs = cfg["llm"], cfg["llm"]["search"], cfg["webfetch"], cfg["docs"]
    search_limiter = RateLimiter(llm["max_calls_per_minute"], SECONDS_PER_MINUTE)
    fetch_limiter = RateLimiter(1, web["request_interval_s"])
    stored = 0
    with (
        httpx.Client(timeout=llm["timeout_s"]) as search_http,
        httpx.Client(timeout=web["timeout_s"], headers={"User-Agent": web["user_agent"]}) as web_http,
    ):
        gemini = GeminiSearch(search["base_url"], search["model"], search_key, search_http)
        pending = sorted(
            (c for c in candidates if not store.has_source(c[0], "web")), key=lambda c: c[1][F.PRIORITY_RANK]
        )
        for done, (ticker, metrics) in enumerate(tqdm(pending)):
            search_limiter.acquire()
            prompt = docs["search_prompt"].format(name=metrics[F.NAME], code=ticker.removesuffix(TICKER_SUFFIX))
            try:
                answer = gemini.search(prompt)
            except QuotaExceeded as e:
                store.record_error(ticker, "web", "search", str(e))
                print(f"Search quota used up: {len(pending) - done} candidates left for the next `docs` run.")
                break
            except LLMError as e:
                store.record_error(ticker, "web", "search", str(e))
                continue
            for _, uri in answer.sources[: docs["max_sources"]]:
                fetch_limiter.acquire()
                stored += fetch_document(uri, ticker, web_http, store, web["max_bytes"]) is not None
    return stored


def run_docs(cfg: dict[str, Any], run_id: str | None):
    key = require_env(cfg["edinet"]["key_env"])
    search_key = require_env(cfg["llm"]["search"]["key_env"]) if cfg["docs"]["search"] else ""
    rec = cfg["records"]
    with RecordStore(ROOT / rec["db_file"], ROOT / rec["export_dir"]) as records:
        run_id = run_id or records.runs()[-1][0]
        candidates = records.candidates(run_id)
    tickers = [t for t, _ in candidates]
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
        web_stored = collect_web_documents(cfg, search_key, candidates, store) if search_key else 0
    failed = sum(not ids for ids in stored)
    summary = f"{sum(map(len, stored))} documents stored for {len(tickers) - failed} tickers; {failed} tickers failed."
    print(f"{summary} {web_stored} web documents stored." if search_key else summary)


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
            [{"role": "user", "content": llm["check"]["chat_prompt"]}]
        )
        print(f"chat: {reply.provider} / {reply.model}, answer {len(reply.text)} chars")
        key = os.environ.get(search["key_env"], "")
        answer = GeminiSearch(search["base_url"], search["model"], key, http).search(llm["check"]["search_prompt"])
        print(f"search: answer {len(answer.text)} chars, {len(answer.sources)} sources, {len(answer.queries)} queries")


def latest_issue(today: datetime.date, months: Sequence[int], release_day: int) -> str:
    """Latest Shikiho issue (``YYYY-MM``) out by ``today``; an issue is out on ``release_day`` of its month."""
    released = [
        (year, month)
        for year in (today.year - 1, today.year)
        for month in months
        if datetime.date(year, month, release_day) <= today
    ]
    return "{}-{:02d}".format(*max(released))


def git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


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
        tk = cfg["tickers"]
        count = update_ticker_csv(out_csv, tk["jpx_url"], tk["markets"], tk["timeout_s"])
        print(f"Saved {count} tickers to {out_csv}")
        return

    if args.command == "calendar":
        out_csv = ROOT / cfg["calendar"]["out_csv"]
        cal = cfg["calendar"]
        count = update_calendar_csv(out_csv, cal["page_url"], cal["link_pattern"], cal["user_agent"], cal["timeout_s"])
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
