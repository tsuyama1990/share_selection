"""The flow of ``flow-memo``: the sources of a demand, the axes taken from them, the map of the beneficiary
companies, the numbers of each company and the Markdown memo that ties them together.

The pure parts (``company_numbers`` and ``render_flow_memo``) decide everything from their arguments; the search,
the page fetches and the LLM are reached only through ``FlowDeps``, which the caller opens and passes in."""

import datetime
import math
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from . import fields as F
from .cache import StockCache, closes_of, price_earnings
from .company_map import CompanyHit, MapDeps, MapSettings, build_map
from .docstore import DocStore
from .flow_store import AxisRow, CompanyRow, DecisionRow, FlowRow, FlowStore
from .llm import GeminiSearch, LLMClient, LLMError
from .memo import PER, PER_FORWARD, CompanyLine, axis_value, render_flow_memo
from .records import RecordStore
from .research import load_prompts, prompt_version, run_task
from .sector import MomentumSettings, Peers, PeerSettings, Universe, compare, momentum, momentum_note
from .throttle import RateLimiter
from .tickers import NAME, SECTOR33, read_column
from .webfetch import fetch_page

AXES_TASK = "axes"  # the task name under prompts/flow/ that asks for the axes; its file is task.lower() + ".md"
OWNER = "flow:{flow_id}"  # documents.ticker of the pages fetched for a flow (they belong to no company)
STAGE1_PASS = "stage1_pass"
FAIL_RULE = "stage1_fail_rule"


@dataclass(frozen=True)
class FlowSettings:
    memo_dir: Path
    prompts_dir: Path
    search_prompt: str
    max_sources: int
    max_doc_chars: int
    max_bytes: int
    axes: tuple[str, ...]
    map: MapSettings
    per_max: float
    momentum: MomentumSettings
    peers: PeerSettings

    @classmethod
    def from_config(cls, cfg: dict[str, Any], root: Path) -> "FlowSettings":
        """``flow:``, the page size of ``webfetch`` and the ``sector:`` values the memo compares with."""
        flow = cfg["flow"]
        return cls(
            memo_dir=root / flow["memo_dir"],
            prompts_dir=root / flow["prompts_dir"],
            search_prompt=flow["search_prompt"],
            max_sources=flow["max_sources"],
            max_doc_chars=flow["max_doc_chars"],
            max_bytes=cfg["webfetch"]["max_bytes"],
            axes=tuple(flow["axes"]),
            map=MapSettings.from_config(cfg),
            per_max=flow["per_max"],
            momentum=MomentumSettings.from_config(cfg),
            peers=PeerSettings.from_config(cfg),
        )


@dataclass(frozen=True)
class Throttles:
    search: RateLimiter  # waits before the search call
    fetch: RateLimiter  # ... and before each page fetch


@dataclass(frozen=True)
class FlowDeps:
    llm: LLMClient
    prompts: dict[str, str]
    search: GeminiSearch
    store: DocStore
    flows: FlowStore
    records: RecordStore
    history: Callable[[str], pd.Series]  # the adjusted daily closes, as outcomes.evaluate gets them
    per: Callable[[str], tuple[float | None, float | None]]  # the trailing and forward PER of the cached quote
    sectors: dict[str, str]  # ticker -> 33-sector (read from the input csv by the caller)
    names: dict[str, str]  # ticker -> company name
    http: httpx.Client
    throttles: Throttles

    @classmethod
    def from_config(
        cls, cfg: dict[str, Any], root: Path, env: Mapping[str, str], stack: ExitStack, settings: FlowSettings
    ) -> "FlowDeps":
        """Open the clients and stores on ``stack``; a missing LLM or search key raises before any store is opened."""
        llm_http = stack.enter_context(httpx.Client(timeout=cfg["llm"]["timeout_s"]))
        web = cfg["webfetch"]
        web_http = stack.enter_context(
            httpx.Client(timeout=web["timeout_s"], headers={"User-Agent": web["user_agent"]})
        )
        llm, search = LLMClient.from_config(cfg, llm_http, env), GeminiSearch.from_config(cfg, llm_http, env)
        csv_path = root / cfg["system"]["input_csv"]
        cache = stack.enter_context(StockCache.from_config(cfg, root))
        return cls(
            llm=llm,
            prompts=load_prompts(settings.prompts_dir),
            search=search,
            store=stack.enter_context(DocStore.from_config(cfg, root)),
            flows=stack.enter_context(FlowStore.from_config(cfg, root)),
            records=stack.enter_context(RecordStore.from_config(cfg, root)),
            history=closes_of(cache),
            per=price_earnings(cache),
            sectors=read_column(csv_path, SECTOR33),
            names=read_column(csv_path, NAME),
            http=web_http,
            throttles=Throttles(
                search=RateLimiter.per_minute(cfg["llm"]["max_calls_per_minute"]),
                fetch=RateLimiter(1, web["request_interval_s"]),
            ),
        )


@dataclass(frozen=True)
class FlowSummary:
    flow_id: str
    memo_path: Path
    unknown_axes: list[str]
    companies: list[str]
    searches_left: int | None  # None: the search was not cut short, so nothing was used up
    ranked: int  # companies the ranking passed to the LLM
    failed: int  # of those, companies whose confirmation failed


class MissingProfilesError(RuntimeError):
    """The document store holds no profile text, so no company can be mapped for the demand."""


@dataclass(frozen=True)
class MemoRequest:
    """The flow the user names: its name, the demand behind it, sources already found and search terms of their own.

    ``terms`` are searched before the LLM's own terms; an automated caller can pass its terms here.
    """

    name: str
    demand: str
    urls: Sequence[str] = ()
    terms: Sequence[str] = ()


def flow_memo(request: MemoRequest, settings: FlowSettings, deps: FlowDeps) -> FlowSummary:
    """The memo of one demand: its sources, axes, company map, the numbers of each company and the file.

    The flow is saved first, so a failure of the axes or the map leaves the row and its documents behind.
    """
    name, demand, urls = request.name, request.demand, request.urls
    flow_id = deps.flows.save_flow(
        FlowRow(name, demand, list(urls), prompt_version(deps.prompts), deps.llm.primary.model)
    )
    owner = OWNER.format(flow_id=flow_id)
    searches_left = _gather(settings.search_prompt.format(name=name, demand=demand), urls, owner, settings, deps)
    axes = _axes(name, demand, owner, settings, deps)
    deps.flows.record_axes(flow_id, axes)
    if not deps.store.profiles(settings.map.sections):
        raise MissingProfilesError("the document store holds no profile text; run `main.py profiles` first")
    mapped = build_map(demand, settings.map, MapDeps(deps.llm, deps.prompts, deps.store), request.terms)
    hits = mapped.hits
    companies, rows = _companies(hits, settings, deps)
    deps.flows.record_companies(flow_id, rows)
    settings.memo_dir.mkdir(parents=True, exist_ok=True)
    memo_path = settings.memo_dir / f"{name}-{datetime.date.today():%Y-%m-%d}.md"
    memo_path.write_text(render_flow_memo(name, demand, axes, companies, mapped.terms), encoding="utf-8")
    unknown = [row.axis for row in axes if axis_value(row) == F.UNKNOWN]
    return FlowSummary(
        flow_id,
        memo_path,
        unknown,
        [line.ticker for line in companies],
        searches_left,
        len(mapped.ranked),
        len(mapped.failed),
    )


def company_numbers(
    ticker: str, row: dict[str, Any], peers: Peers, momentum: dict[str, Any], per_max: float
) -> dict[str, Any]:
    """The numbers of one mapped company: its screen row, its sector comparison and its momentum.

    An item the run record does not hold is ``None``. The lower of the trailing and forward PER at or above
    ``per_max`` marks the company as overvalued (a one-off drop in profit or a data error in one of them does not),
    while a company with neither PER (a loss, say) never is.
    """
    per, per_forward = _finite(row.get(PER)), _finite(row.get(PER_FORWARD))
    known = [value for value in (per, per_forward) if value is not None]
    return {
        "stage1_pass": row.get(STAGE1_PASS),
        "fail_rule": row.get(FAIL_RULE),
        "improvement_class": row.get(F.IMPROVEMENT_CLASS),
        "sector_comparison": compare(ticker, row, peers),
        "position": momentum.get("position"),
        "per": per,
        "per_forward": per_forward,
        "overvalued": bool(known) and min(known) >= per_max,
    }


def _gather(query: str, urls: Sequence[str], owner: str, settings: FlowSettings, deps: FlowDeps) -> int | None:
    """Fetch the caller's urls and the first cited sources; ``0`` left when the search gave nothing.

    A used-up quota and a failed search (a 503 under load) both leave only the caller's urls: the flow goes on.
    """
    try:
        deps.throttles.search.acquire()
        answer = deps.search.search(query)
    except LLMError:  # QuotaExceeded is one of them
        _fetch(urls, owner, settings, deps)
        return 0
    cited = [uri for _title, uri in answer.sources[: settings.max_sources] if uri]
    _fetch([*urls, *cited], owner, settings, deps)
    return None


def _fetch(urls: Sequence[str], owner: str, settings: FlowSettings, deps: FlowDeps) -> None:
    """Store each page under ``owner``; a page that fails is recorded by ``webfetch`` and skipped."""
    for url in dict.fromkeys(urls):
        deps.throttles.fetch.acquire()
        fetch_page(url, deps.http, deps.store, settings.max_bytes, owner)


def _axes(name: str, demand: str, owner: str, settings: FlowSettings, deps: FlowDeps) -> list[AxisRow]:
    """The axes extracted from the documents of the flow; an unverifiable item stays ``fields.UNKNOWN``."""
    docs = {doc.doc_id: doc.text[: settings.max_doc_chars] for doc in deps.store.documents(owner)}
    context = {"name": name, "demand": demand}
    result = run_task(deps.llm, deps.prompts, (AXES_TASK, list(settings.axes)), docs, context)
    ratio = len(result.evidence) / result.claims if result.claims else 0.0
    return [
        AxisRow(axis, {"value": result.answer.get(axis)}, [c for c in result.evidence if c["field"] == axis], ratio)
        for axis in settings.axes
    ]


def _companies(
    hits: list[CompanyHit], settings: FlowSettings, deps: FlowDeps
) -> tuple[list[CompanyLine], list[CompanyRow]]:
    """One line and one row per mapped company: its screen row, its sector comparison and its momentum."""
    run_id = deps.records.resolve_run(None)
    metrics = deps.records.run_metrics(run_id)
    peers = Peers.build(metrics, deps.sectors, settings.peers)
    universe = Universe(deps.history, peers.tickers, deps.sectors)
    today = datetime.date.today()
    lines: list[CompanyLine] = []
    rows: list[CompanyRow] = []
    for hit in hits:
        per, per_forward = deps.per(hit.ticker)
        row = {**deps.records.screen_row(run_id, hit.ticker), PER: per, PER_FORWARD: per_forward}
        mom = momentum(universe, hit.ticker, settings.momentum, today)
        numbers = company_numbers(hit.ticker, row, peers, mom, settings.per_max)
        lines.append(
            CompanyLine(
                hit.ticker,
                deps.names.get(hit.ticker, hit.ticker),
                hit.tier,
                hit.exposure,
                numbers,
                momentum_note(mom, settings.momentum),
            )
        )
        rows.append(
            CompanyRow(
                ticker=hit.ticker,
                tier=hit.tier,
                exposure=hit.exposure,
                evidence=hit.evidence,
                run_id=run_id,
                stage1_pass=bool(row.get(STAGE1_PASS)),
                fail_rule=row.get(FAIL_RULE),
                valuations=numbers,
                past3m_rank=mom.get("industry_rank"),
            )
        )
    return lines, rows


ACTIONS = ("buy", "skip")


@dataclass(frozen=True)
class Decision:
    """A human decision on one company of a flow; a cap of 0 yen differs from no cap (None)."""

    flow_id: str
    ticker: str
    action: str
    reason: str
    max_yen: int | None

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"action must be one of {', '.join(ACTIONS)}: {self.action}")
        if self.max_yen is not None and self.max_yen < 0:
            raise ValueError(f"max yen must not be negative: {self.max_yen}")


def flow_decide(decision: Decision, flows: FlowStore) -> None:
    """Record the decision at the current minute (a skip is recorded too)."""
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    flows.record_decision(
        DecisionRow(decision.flow_id, decision.ticker, now, decision.action, decision.reason, decision.max_yen)
    )


def _finite(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )
