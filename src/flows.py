"""CLI flows that compose several components: `docs`, `profiles` and `review` on a recorded run, and `flow-memo`
on a flow the user names."""

import datetime
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .cache import StockCache, closes_of
from .collect import CollectClients, CollectSettings, collect_documents, collect_profiles, companies
from .docstore import DocStore
from .flow import FlowDeps, FlowSettings, Throttles, flow_memo
from .flow_store import FlowStore
from .llm import GeminiSearch, LLMClient
from .records import RecordStore
from .research import load_prompts, prompt_version
from .review import ReviewDeps, ReviewSettings, review_candidates
from .sector import Peers
from .throttle import RateLimiter
from .tickers import NAME, SECTOR33, read_column


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
        peers = Peers.from_run(records, run_id, sectors, cfg)
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
    csv_path = root / cfg["system"]["input_csv"]
    with ExitStack() as stack:
        llm_http = stack.enter_context(httpx.Client(timeout=cfg["llm"]["timeout_s"]))
        web_http = stack.enter_context(
            httpx.Client(timeout=cfg["webfetch"]["timeout_s"], headers={"User-Agent": cfg["webfetch"]["user_agent"]})
        )
        deps = FlowDeps(
            llm=LLMClient.from_config(cfg, llm_http, env),
            prompts=load_prompts(settings.prompts_dir),
            search=GeminiSearch.from_config(cfg, llm_http, env),
            store=stack.enter_context(DocStore.from_config(cfg, root)),
            flows=stack.enter_context(FlowStore.from_config(cfg, root)),
            records=stack.enter_context(RecordStore.from_config(cfg, root)),
            history=closes_of(stack.enter_context(StockCache.from_config(cfg, root))),
            sectors=read_column(csv_path, SECTOR33),
            names=read_column(csv_path, NAME),
            http=web_http,
            throttles=Throttles(
                search=RateLimiter.per_minute(cfg["llm"]["max_calls_per_minute"]),
                fetch=RateLimiter(1, cfg["webfetch"]["request_interval_s"]),
            ),
        )
        summary = flow_memo(request.name, request.demand, request.urls, settings, deps)
    print(
        f"Flow memo written to {summary.memo_path}: "
        f"{len(summary.companies)} companies, {len(summary.unknown_axes)} axes unknown, "
        f"{summary.ranked} ranked, {summary.failed} failed to confirm."
    )
    if summary.searches_left is not None:
        print("Search quota used up: only the `--url` sources were collected.")
