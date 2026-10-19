"""CLI flows that compose several components: `docs`, `profiles` and `review` on a recorded run, and `flow-memo`
on a flow the user names."""

import datetime
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache import StockCache, refresh_all
from .collect import CollectClients, CollectSettings, collect_documents, collect_profiles, companies
from .docstore import WEB, DocStore
from .earnings_calendar import load_calendar
from .flow import FlowDeps, FlowSettings, flow_memo
from .records import RecordStore, RunInfo, git_sha
from .report import format_eval, write_failures, write_report
from .research import prompt_version
from .review import ReviewDeps, ReviewSettings, review_candidates
from .review_eval import evaluate_model, load_eval_cases
from .screener import NO_CACHE, Screener, screen_universe
from .sector import Peers, PeerSettings
from .selection import prioritize
from .tickers import NAME, SECTOR33, read_column
from .yahoo import YahooClient

EVAL_RUN_ID = "eval-%Y%m%dT%H%M%S"


class EvalNotPassedError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemoRequest:
    """The flow the user names: its name, the demand behind it and the sources they already found."""

    name: str
    demand: str
    urls: Sequence[str]


def collect_run(cfg: dict[str, Any], root: Path, env: Mapping[str, str], run: str | None, today: datetime.date) -> None:
    """Collect the documents of the stage 2 candidates of run ``run`` (default: the latest) and print a summary."""
    with ExitStack() as stack:
        clients = CollectClients.from_config(cfg, env, stack, cfg["docs"]["search"])
        with RecordStore.from_config(cfg, root) as records:
            run_id = records.resolve_run(run)
            candidates = records.candidates(run_id)
        print(f"Collecting documents of {len(candidates)} candidates of run {run_id}...")
        names = read_column(root / cfg["system"]["input_csv"], NAME)
        store = stack.enter_context(DocStore.from_config(cfg, root))
        summary = collect_documents(
            companies(candidates, names), CollectSettings.from_config(cfg), clients, store, today
        )
    if summary.searches_left:
        print(f"Search quota used up: {summary.searches_left} candidates left for the next `docs` run.")
    text = f"{summary.edinet_docs} documents stored for {len(candidates) - summary.edinet_failed} tickers; "
    text += f"{summary.edinet_failed} tickers failed."
    print(f"{text} {summary.web_docs} web documents stored." if clients.search else text)


def profiles_run(
    cfg: dict[str, Any], root: Path, env: Mapping[str, str], tickers: list[str], today: datetime.date
) -> None:
    """Collect the EDINET annual report sections of every ticker and print a summary."""
    with ExitStack() as stack:
        clients = CollectClients.from_config(cfg, env, stack, False)
        store = stack.enter_context(DocStore.from_config(cfg, root))
        summary = collect_profiles(tickers, CollectSettings.from_config(cfg), clients, store, today)
    print(f"{summary.edinet_docs} reports stored, {summary.edinet_failed} failed.")


def review_run(
    cfg: dict[str, Any], root: Path, env: Mapping[str, str], run: str | None, tickers: list[str] | None
) -> None:
    """Review the candidates of run ``run`` (default: the latest) and print a summary; refuse unless this prompt and
    model passed the eval."""
    sectors = read_column(root / cfg["system"]["input_csv"], SECTOR33)
    with RecordStore.from_config(cfg, root) as records:
        run_id = records.resolve_run(run)
        candidates = records.candidates(run_id)
        peers = Peers.build(records.run_metrics(run_id), sectors, PeerSettings.from_config(cfg))
    with ExitStack() as stack:
        deps = ReviewDeps.from_config(cfg, root, env, stack, peers)
        version, model = prompt_version(deps.prompts), deps.llm.primary.model
        if not deps.reviews.passed_eval(version, model):
            raise EvalNotPassedError(f"no passed review-eval for prompt {version} / {model}; run `review-eval` first")
        summary = review_candidates(run_id, candidates, tickers, ReviewSettings.from_config(cfg), deps)
    print(
        f"Run {run_id}: {summary.reviewed} reviewed, {summary.failed} failed, {summary.needs_attention} need attention."
    )
    print(f"Memos written to {deps.memo_dir}.")


def flow_memo_run(cfg: dict[str, Any], root: Path, env: Mapping[str, str], request: MemoRequest) -> None:
    """Research the flow the user names (sources, axes, map, numbers) and print where the memo went."""
    settings = FlowSettings.from_config(cfg, root)
    with ExitStack() as stack:
        deps = FlowDeps.from_config(cfg, root, env, stack, settings)
        summary = flow_memo(request.name, request.demand, request.urls, settings, deps)
    print(
        f"Flow memo written to {summary.memo_path}: "
        f"{len(summary.companies)} companies, {len(summary.unknown_axes)} axes unknown, "
        f"{summary.ranked} ranked, {summary.failed} failed to confirm."
    )
    if summary.searches_left is not None:
        print("Search quota used up: only the `--url` sources were collected.")


def fetch_run(cfg: dict[str, Any], root: Path, tickers: list[str]) -> None:
    """Refresh the cache from Yahoo and write the failures CSV."""
    print(f"Starting Data Fetch for {len(tickers)} stocks...")
    with StockCache.from_config(cfg, root) as cache:
        failures = refresh_all(cache, YahooClient.from_config(cfg), tickers, cfg["system"]["cache_days"])
    print(f"fetched {len(tickers) - len(failures)} / {len(tickers)}")
    if failures:
        write_failures(failures, root / cfg["output"]["dir"], cfg["output"]["failures_filename"])


def analyze_run(cfg: dict[str, Any], root: Path, tickers: list[str], issue: str) -> None:
    """Screen the cached universe, record the run and write the result CSV."""
    print(f"Starting Analysis for {len(tickers)} stocks (using cache)...")
    output_cfg = cfg["output"]
    with StockCache.from_config(cfg, root) as cache:
        calendar = load_calendar(root / cfg["calendar"]["out_csv"])
        results = screen_universe(tickers, cache, Screener.from_config(cfg), calendar)
        fetched_min, fetched_max = cache.fetched_range()
    passed = [r.row for r in results.values() if r.passed]
    prioritize(passed, cfg["selection"]["candidates_n"])
    list_date = datetime.date.fromtimestamp((root / cfg["system"]["input_csv"]).stat().st_mtime)
    with RecordStore.from_config(cfg, root) as store:
        run_id = store.record_run(RunInfo(issue, git_sha(), cfg, list_date, fetched_min, fetched_max), results)
    print(f"Recorded run {run_id} ({len(results)} tickers).")
    if no_cache := sum(r.fail_rule == NO_CACHE for r in results.values()):
        print(f"{no_cache} tickers had no cache (run `fetch` first).")
    if not passed:
        print("No stocks passed the Gatekeeper.")
        return
    write_report(passed, root / output_cfg["dir"], output_cfg["filename"], output_cfg["columns"])


def review_eval_run(cfg: dict[str, Any], root: Path, env: Mapping[str, str]) -> bool:
    """Score the model on the eval cases, record and print the result; True when it passed."""
    rev = cfg["review"]
    cases = load_eval_cases(root / rev["eval"]["cases_file"])
    with ExitStack() as stack:
        clients = CollectClients.from_config(cfg, env, stack, WEB in rev["eval"]["sources"])
        deps = ReviewDeps.from_config(cfg, root, env, stack, None)
        companies = [c.company for c in cases]
        collect_documents(companies, CollectSettings.from_config(cfg), clients, deps.store, datetime.date.today())
        outcomes = evaluate_model(cases, cfg, deps, datetime.datetime.now().strftime(EVAL_RUN_ID))
        lines, overall = format_eval(outcomes, deps.llm.primary.model)
        print("\n".join(lines))
        summary = [{"run": n, "hits": r.hits, "passed": r.passed} for n, (_, r) in enumerate(outcomes, 1)]
        deps.reviews.record_eval(prompt_version(deps.prompts), deps.llm.primary.model, overall, summary)
    return overall.passed
