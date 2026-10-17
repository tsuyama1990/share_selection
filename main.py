import argparse
import datetime
import os
import sys
from collections.abc import Callable
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from src import fields as F
from src.cache import StockCache, refresh_all
from src.collect import CollectClients, CollectSettings, collect_documents
from src.config import CONFIG_FILE, ROOT, MissingKeyError, load_config
from src.docstore import DocStore
from src.earnings_calendar import load_calendar, update_calendar_csv
from src.llm import GeminiSearch, LLMClient
from src.records import RecordStore, RunInfo, evaluate, git_sha, latest_issue
from src.report import write_failures, write_report
from src.research import load_prompts
from src.review import ReviewDeps, ReviewSettings, review_candidates
from src.review_eval import EvalCase, EvalResult, judge, load_eval_cases, score_case
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
        output_cfg = cfg["output"]
        path = write_failures(failures, ROOT / output_cfg["dir"], output_cfg["failures_filename"])
        print(f"{len(failures)} fetch failures saved to {path}")


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
    rec, client = cfg["records"], YahooClient.from_config(cfg)
    with RecordStore.from_config(cfg, ROOT) as store:
        earliest = min((at for _, at in store.runs()), default=datetime.datetime.now())
        start = (earliest - datetime.timedelta(days=rec["price_lookback_days"])).date()
        history = partial(client.adjusted_close, start=start)
        added = evaluate(store, history, rec["horizons_months"], rec["benchmark_ticker"], datetime.datetime.now())
    print(f"Added {added} outcome rows.")


def cmd_docs(cfg: Cfg, args: Args) -> None:
    with ExitStack() as stack:
        clients = CollectClients.from_config(cfg, os.environ, stack)
        with RecordStore.from_config(cfg, ROOT) as records:
            run_id = args.run or records.runs()[-1][0]
            candidates = records.candidates(run_id)
        print(f"Collecting documents of {len(candidates)} candidates of run {run_id}...")
        store = stack.enter_context(DocStore.from_config(cfg, ROOT))
        summary = collect_documents(candidates, CollectSettings.from_config(cfg), clients, store, datetime.date.today())
    if summary.searches_left:
        print(f"Search quota used up: {summary.searches_left} candidates left for the next `docs` run.")
    text = f"{summary.edinet_docs} documents stored for {len(candidates) - summary.edinet_failed} tickers; "
    text += f"{summary.edinet_failed} tickers failed."
    print(f"{text} {summary.web_docs} web documents stored." if clients.search else text)


def open_review(cfg: Cfg, stack: ExitStack) -> ReviewDeps:
    """The parts of a review run, opened on ``stack``; a missing LLM key raises before any record is read."""
    http = stack.enter_context(httpx.Client(timeout=cfg["llm"]["timeout_s"]))
    llm = LLMClient.from_config(cfg, http, os.environ)
    prompts = load_prompts(ROOT / cfg["review"]["prompt_dir"])
    return ReviewDeps(
        llm,
        prompts,
        stack.enter_context(RecordStore.from_config(cfg, ROOT)),
        stack.enter_context(DocStore.from_config(cfg, ROOT)),
    )


def cmd_review(cfg: Cfg, args: Args) -> None:
    version = cfg["review"]["prompt_version"]
    with ExitStack() as stack:
        deps = open_review(cfg, stack)
        model = deps.llm.primary_model
        if not deps.records.passed_eval(version, model):
            print(f"Error: no passed review-eval for prompt {version} / {model}; run `review-eval` first.")
            sys.exit(1)
        run_id = args.run or deps.records.runs()[-1][0]
        tickers = args.tickers.split(",") if args.tickers else None
        candidates = deps.records.candidates(run_id)
        summary = review_candidates(run_id, candidates, tickers, ReviewSettings.from_config(cfg), deps)
    print(
        f"Run {run_id}: {summary.reviewed} reviewed, {summary.failed} failed, {summary.needs_attention} need attention."
    )


def print_eval(results: list[tuple[EvalCase, bool]], result: EvalResult, model: str) -> None:
    for case, hit in results:
        print(f"  {'hit ' if hit else 'MISS'} {case.ticker} {case.task}.{case.field} {case.expect_any}: {case.basis}")
    print(
        f"review-eval {model}: {result.hits}/{result.cases} cases, {result.parse_failures} parse failures, "
        f"lowest verified ratio {result.min_verified_ratio:.2f}: {'PASSED' if result.passed else 'FAILED'}"
    )


def cmd_review_eval(cfg: Cfg, args: Args) -> None:
    rev = cfg["review"]
    cases = load_eval_cases(ROOT / rev["eval"]["cases_file"])
    names = {c.ticker: c.name for c in cases}
    candidates = [(t, {F.NAME: n, F.PRIORITY_RANK: rank}) for rank, (t, n) in enumerate(names.items(), 1)]
    run_id = datetime.datetime.now().strftime(EVAL_RUN_ID)
    with ExitStack() as stack:
        clients = CollectClients.from_config(cfg, os.environ, stack)
        deps = open_review(cfg, stack)
        collect_documents(candidates, CollectSettings.from_config(cfg), clients, deps.store, datetime.date.today())
        review_candidates(run_id, candidates, None, ReviewSettings.from_config(cfg), deps)
        rows = deps.records.reviews(run_id)
        results = [(c, score_case(c, rows[c.ticker])) for c in cases]
        thresholds = {**rev["eval"], "min_verified_ratio": rev["min_verified_ratio"]}
        result = judge(results, list(rows.values()), thresholds)
        summary = [{"ticker": c.ticker, "task": c.task, "field": c.field, "hit": hit} for c, hit in results]
        model = deps.llm.primary_model
        deps.records.record_eval(rev["prompt_version"], model, result, summary)
    print_eval(results, result, model)
    if not result.passed:
        sys.exit(1)


def cmd_llm_check(cfg: Cfg, args: Args) -> None:
    """Smoke test: one prompt through the fallback chain and one grounded search; prints no secrets."""
    check = cfg["llm"]["check"]
    with httpx.Client(timeout=cfg["llm"]["timeout_s"]) as http:
        reply = LLMClient.from_config(cfg, http, os.environ).chat([{"role": "user", "content": check["chat_prompt"]}])
        print(f"chat: {reply.provider} / {reply.model}, answer {len(reply.text)} chars")
        answer = GeminiSearch.from_config(cfg, http, os.environ).search(check["search_prompt"])
        print(f"search: answer {len(answer.text)} chars, {len(answer.sources)} sources, {len(answer.queries)} queries")


COMMANDS: dict[str, tuple[Callable[[Cfg, Args], None], str]] = {
    "tickers": (cmd_tickers, "Update the ticker CSV from the JPX listed company list"),
    "calendar": (cmd_calendar, "Update the earnings calendar CSV from the JPX announcement schedule"),
    "fetch": (cmd_fetch, "Fetch data from Yahoo Finance"),
    "analyze": (cmd_analyze, "Analyze cached data and record the run"),
    "evaluate": (cmd_evaluate, "Compute outcomes of recorded runs whose horizons have elapsed"),
    "docs": (cmd_docs, "Collect EDINET annual report sections and web sources of a run's stage 2 candidates"),
    "review": (cmd_review, "LLM research on a run's stage 2 candidates (needs a passed review-eval)"),
    "review-eval": (cmd_review_eval, "Score the model and prompt version on tickers with known answers"),
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
    except MissingKeyError as e:
        print(f"Error: {e}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
