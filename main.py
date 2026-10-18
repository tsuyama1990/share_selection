import argparse
import datetime
import os
import sys
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.backup import BackupInsideRepoError, backup_from_config
from src.cache import StockCache, refresh_all
from src.collect import CollectClients, CollectSettings, collect_documents
from src.config import CONFIG_FILE, ROOT, MissingKeyError, load_config
from src.earnings_calendar import load_calendar, update_calendar_csv
from src.flows import EvalNotPassedError, collect_run, profiles_run, review_run
from src.llm import smoke_check
from src.outcomes import evaluate_recorded
from src.records import RecordStore, RunInfo, git_sha, latest_issue
from src.report import format_eval, write_failures, write_report
from src.research import prompt_version
from src.review import ReviewDeps
from src.review_eval import evaluate_model, load_eval_cases
from src.screener import NO_CACHE, Screener, screen_universe
from src.selection import prioritize
from src.tickers import read_tickers, update_ticker_csv
from src.yahoo import YahooClient

Args = argparse.Namespace
Cfg = dict[str, Any]
EVAL_RUN_ID = "eval-%Y%m%dT%H%M%S"


def read_universe(cfg: Cfg) -> list[str]:
    csv_path = ROOT / cfg["system"]["input_csv"]
    if not csv_path.exists():
        print(f"Error: ticker CSV not found: {csv_path} (run `tickers`)")
        sys.exit(1)
    print(f"Reading tickers from {csv_path}...")
    return read_tickers(csv_path)


def default_issue(cfg: Cfg) -> str:
    rec = cfg["records"]
    return latest_issue(datetime.date.today(), rec["shikiho_issue_months"], rec["shikiho_release_day"])


def cmd_tickers(cfg: Cfg, args: Args) -> None:
    out_csv, tk = ROOT / cfg["system"]["input_csv"], cfg["tickers"]
    print(f"Saved {update_ticker_csv(out_csv, tk['jpx_url'], tk['markets'], tk['timeout_s'])} tickers to {out_csv}")


def cmd_calendar(cfg: Cfg, args: Args) -> None:
    out_csv, cal = ROOT / cfg["calendar"]["out_csv"], cfg["calendar"]
    count = update_calendar_csv(out_csv, cal["page_url"], cal["link_pattern"], cal["user_agent"], cal["timeout_s"])
    print(f"Saved {count} announcement dates to {out_csv}")


def cmd_fetch(cfg: Cfg, args: Args) -> None:
    tickers = read_universe(cfg)
    print(f"Starting Data Fetch for {len(tickers)} stocks...")
    with StockCache.from_config(cfg, ROOT) as cache:
        failures = refresh_all(cache, YahooClient.from_config(cfg), tickers, cfg["system"]["cache_days"])
    print(f"fetched {len(tickers) - len(failures)} / {len(tickers)}")
    if failures:
        write_failures(failures, ROOT / cfg["output"]["dir"], cfg["output"]["failures_filename"])


def cmd_analyze(cfg: Cfg, args: Args) -> None:
    tickers = read_universe(cfg)
    print(f"Starting Analysis for {len(tickers)} stocks (using cache)...")
    output_cfg = cfg["output"]
    with StockCache.from_config(cfg, ROOT) as cache:
        calendar = load_calendar(ROOT / cfg["calendar"]["out_csv"])
        results = screen_universe(tickers, cache, Screener.from_config(cfg), calendar)
        fetched_min, fetched_max = cache.fetched_range()
    passed = [r.row for r in results.values() if r.passed]
    prioritize(passed, cfg["selection"]["candidates_n"])
    issue = args.issue or default_issue(cfg)
    list_date = datetime.date.fromtimestamp((ROOT / cfg["system"]["input_csv"]).stat().st_mtime)
    with RecordStore.from_config(cfg, ROOT) as store:
        run_id = store.record_run(RunInfo(issue, git_sha(), cfg, list_date, fetched_min, fetched_max), results)
    print(f"Recorded run {run_id} ({len(results)} tickers).")
    if no_cache := sum(r.fail_rule == NO_CACHE for r in results.values()):
        print(f"{no_cache} tickers had no cache (run `fetch` first).")
    if not passed:
        print("No stocks passed the Gatekeeper.")
        return
    write_report(passed, ROOT / output_cfg["dir"], output_cfg["filename"], output_cfg["columns"])


def cmd_evaluate(cfg: Cfg, args: Args) -> None:
    added = evaluate_recorded(cfg, ROOT, YahooClient.from_config(cfg), datetime.datetime.now())
    print(f"Added {added} outcome rows.")


def cmd_docs(cfg: Cfg, args: Args) -> None:
    collect_run(cfg, ROOT, os.environ, args.run, datetime.date.today())


def cmd_profiles(cfg: Cfg, args: Args) -> None:
    profiles_run(cfg, ROOT, os.environ, read_universe(cfg), datetime.date.today())


def cmd_review(cfg: Cfg, args: Args) -> None:
    review_run(cfg, ROOT, os.environ, args.run, args.tickers.split(",") if args.tickers else None)


def cmd_review_eval(cfg: Cfg, args: Args) -> None:
    rev = cfg["review"]
    cases = load_eval_cases(ROOT / rev["eval"]["cases_file"])
    with ExitStack() as stack:
        clients = CollectClients.from_config(cfg, os.environ, stack, "web" in rev["eval"]["sources"])
        deps = ReviewDeps.from_config(cfg, ROOT, os.environ, stack, None)
        companies = [c.company for c in cases]
        collect_documents(companies, CollectSettings.from_config(cfg), clients, deps.store, datetime.date.today())
        outcomes = evaluate_model(cases, cfg, deps, datetime.datetime.now().strftime(EVAL_RUN_ID))
        lines, overall = format_eval(outcomes, deps.llm.primary.model)
        print("\n".join(lines))
        summary = [{"run": n, "hits": r.hits, "passed": r.passed} for n, (_, r) in enumerate(outcomes, 1)]
        deps.reviews.record_eval(prompt_version(deps.prompts), deps.llm.primary.model, overall, summary)
    if not overall.passed:
        sys.exit(1)


def cmd_backup(cfg: Cfg, args: Args) -> None:
    try:
        snapshot = backup_from_config(cfg, ROOT, datetime.datetime.now())
    except BackupInsideRepoError:
        print("Error: backup.dir must be outside the repository (it is public).")
        sys.exit(1)
    print(f"Backed up {len(snapshot.copied)} sources to {snapshot.path}.")
    for source in snapshot.skipped:
        print(f"Skipped (missing): {source}")


def cmd_llm_check(cfg: Cfg, args: Args) -> None:
    for line in smoke_check(cfg, os.environ):
        print(line)


COMMANDS: dict[str, tuple[Callable[[Cfg, Args], None], str]] = {
    "tickers": (cmd_tickers, "Update the ticker CSV from the JPX listed company list"),
    "calendar": (cmd_calendar, "Update the earnings calendar CSV from the JPX announcement schedule"),
    "fetch": (cmd_fetch, "Fetch data from Yahoo Finance"),
    "analyze": (cmd_analyze, "Analyze cached data and record the run"),
    "evaluate": (cmd_evaluate, "Compute outcomes of recorded runs whose horizons have elapsed"),
    "docs": (cmd_docs, "Collect EDINET annual report sections and web sources of a run's stage 2 candidates"),
    "profiles": (cmd_profiles, "Store the EDINET annual report sections of every ticker"),
    "review": (cmd_review, "LLM research on a run's stage 2 candidates (needs a passed review-eval)"),
    "review-eval": (cmd_review_eval, "Score the model and prompt version on tickers with known answers"),
    "backup": (cmd_backup, "Copy the ignored records (reviews, memos, document store) outside the repository"),
    "llm-check": (cmd_llm_check, "Smoke-test the LLM fallback chain and Gemini search"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emin Yurumazu Screener")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE, help="Config file (default: config.yaml)")
    sub = parser.add_subparsers(dest="command", help="Commands")
    commands = {name: sub.add_parser(name, help=text) for name, (_, text) in COMMANDS.items()}
    commands["analyze"].add_argument(
        "--issue", help="Shikiho issue (YYYY-MM) the ticker research is based on (default: latest released)"
    )
    commands["docs"].add_argument("--run", help="Run id (default: the latest run)")
    commands["review"].add_argument("--run", help="Run id (default: the latest run)")
    commands["review"].add_argument(
        "--tickers", help="Comma-separated tickers to review (default: the unreviewed candidates)"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config(args.config)
    if args.command is None:
        parser.print_help()
        return
    try:
        COMMANDS[args.command][0](cfg, args)
    except (MissingKeyError, EvalNotPassedError) as e:
        print(f"Error: {e}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
