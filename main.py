import argparse
import datetime
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.backup import BackupInsideRepoError, backup_from_config
from src.config import CONFIG_FILE, ROOT, MissingKeyError, load_config
from src.earnings_calendar import update_calendar_csv
from src.flow import Decision, MissingProfilesError, flow_decide
from src.flow_store import FlowStore
from src.flows import (
    EvalNotPassedError,
    MemoRequest,
    analyze_run,
    collect_run,
    fetch_run,
    flow_memo_run,
    profiles_run,
    review_eval_run,
    review_run,
)
from src.llm import smoke_check
from src.outcomes import evaluate_recorded
from src.records import latest_issue
from src.tickers import read_tickers, update_ticker_csv
from src.yahoo import YahooClient

Args = argparse.Namespace
Cfg = dict[str, Any]


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
    fetch_run(cfg, ROOT, read_universe(cfg))


def cmd_analyze(cfg: Cfg, args: Args) -> None:
    analyze_run(cfg, ROOT, read_universe(cfg), args.issue or default_issue(cfg))


def cmd_evaluate(cfg: Cfg, args: Args) -> None:
    added = evaluate_recorded(cfg, ROOT, YahooClient.from_config(cfg), datetime.datetime.now())
    print(f"Added {added} outcome rows.")


def cmd_docs(cfg: Cfg, args: Args) -> None:
    collect_run(cfg, ROOT, os.environ, args.run, datetime.date.today())


def cmd_profiles(cfg: Cfg, args: Args) -> None:
    tickers = (
        [t if t.endswith(".T") else f"{t}.T" for t in args.tickers.split(",")] if args.tickers else read_universe(cfg)
    )
    profiles_run(cfg, ROOT, os.environ, tickers, datetime.date.today())


def cmd_review(cfg: Cfg, args: Args) -> None:
    review_run(cfg, ROOT, os.environ, args.run, args.tickers.split(",") if args.tickers else None)


def cmd_review_eval(cfg: Cfg, args: Args) -> None:
    if not review_eval_run(cfg, ROOT, os.environ):
        sys.exit(1)


def cmd_flow_memo(cfg: Cfg, args: Args) -> None:
    flow_memo_run(cfg, ROOT, os.environ, MemoRequest(args.name, args.demand, args.url))


def cmd_flow_decide(cfg: Cfg, args: Args) -> None:
    with FlowStore.from_config(cfg, ROOT) as flows:
        flow_decide(Decision(args.flow, args.ticker, args.action, args.reason, args.max_yen), flows)
    print(f"Decision recorded: {args.flow} {args.ticker} {args.action}.")


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
    "evaluate": (cmd_evaluate, "Compute outcomes of recorded runs and decisions whose horizons have elapsed"),
    "docs": (cmd_docs, "Collect EDINET annual report sections and web sources of a run's stage 2 candidates"),
    "profiles": (cmd_profiles, "Store the EDINET annual report sections of every ticker"),
    "review": (cmd_review, "LLM research on a run's stage 2 candidates (needs a passed review-eval)"),
    "review-eval": (cmd_review_eval, "Score the model and prompt version on tickers with known answers"),
    "flow-memo": (cmd_flow_memo, "Research a flow the user names and write its memo (run `profiles` first)"),
    "flow-decide": (cmd_flow_decide, "Record a decision (buy or skip) on a flow's company"),
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
    commands["profiles"].add_argument("--tickers", help="Comma-separated codes (default: every listed ticker)")
    commands["review"].add_argument("--run", help="Run id (default: the latest run)")
    commands["review"].add_argument(
        "--tickers", help="Comma-separated tickers to review (default: the unreviewed candidates)"
    )
    commands["flow-memo"].add_argument("--name", required=True, help="Name of the flow")
    commands["flow-memo"].add_argument("--demand", required=True, help="The demand the flow stands for")
    commands["flow-memo"].add_argument(
        "--url", action="append", default=[], help="A source the user already found (repeatable)"
    )
    commands["flow-decide"].add_argument("--flow", required=True, help="Flow id (from `flow-memo`)")
    commands["flow-decide"].add_argument("--ticker", required=True, help="Ticker code")
    commands["flow-decide"].add_argument("--action", required=True, choices=["buy", "skip"], help="buy or skip")
    commands["flow-decide"].add_argument("--reason", required=True, help="Why")
    commands["flow-decide"].add_argument(
        "--max-yen",
        type=int,
        default=None,
        help="Upper bound of the amount to buy (0 means buy nothing; omit for none)",
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
    except MissingProfilesError:
        print("Error: the document store holds no profile text. Run `profiles` first.")
        sys.exit(1)
    except (MissingKeyError, EvalNotPassedError, ValueError) as e:
        print(f"Error: {e}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
