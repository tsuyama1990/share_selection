"""The flow of ``flow-memo``: the sources of a demand, the axes taken from them, the map of the beneficiary
companies, the numbers of each company and the Markdown memo that ties them together.

The pure parts (``company_numbers`` and ``render_flow_memo``) decide everything from their arguments; the search,
the page fetches and the LLM are reached only through ``FlowDeps``, which the caller opens and passes in."""

import datetime
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from . import fields as F
from .company_map import CompanyHit, MapDeps, MapSettings, build_map
from .docstore import DocStore
from .flow_store import AxisRow, CompanyRow, FlowRow, FlowStore
from .llm import GeminiSearch, LLMClient, QuotaExceeded
from .records import RecordStore
from .research import prompt_version, run_task
from .sector import MomentumSettings, Peers, Universe, compare, momentum, momentum_note, sector_medians
from .throttle import RateLimiter
from .webfetch import fetch_page

AXES_TASK = "axes"  # the task name under prompts/flow/ that asks for the axes; its file is task.lower() + ".md"
OWNER = "flow:{flow_id}"  # documents.ticker of the pages fetched for a flow (they belong to no company)
PER = "PER"  # the trailing PER of the cache, shown as it is (not a report column)
STAGE1_PASS = "stage1_pass"
FAIL_RULE = "stage1_fail_rule"
PER_MARK = "超割高"
COLUMNS = ("コード", "名前", "何次", "売上比率", "業種", "改善区分", "通過", "落ちた条件", "位置", "PER", "比較")
NOTE = "先に上がった会社はその後負けやすい"


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
    sector_metrics: tuple[str, ...]
    min_peers: int

    @classmethod
    def from_config(cls, cfg: dict[str, Any], root: Path) -> "FlowSettings":
        """``flow:``, the page size of ``webfetch`` and the ``sector:`` values the memo compares with."""
        flow = cfg["flow"]
        sector = cfg["sector"]
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
            sector_metrics=tuple(sector["metrics"]),
            min_peers=sector["min_peers"],
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
    sectors: dict[str, str]  # ticker -> 33-sector (read from the input csv by the caller)
    names: dict[str, str]  # ticker -> company name
    http: httpx.Client
    throttles: Throttles


@dataclass(frozen=True)
class FlowSummary:
    flow_id: str
    memo_path: Path
    unknown_axes: list[str]
    companies: list[str]
    searches_left: int | None  # None: the search was not cut short, so nothing was used up


@dataclass(frozen=True)
class CompanyLine:
    ticker: str
    name: str
    tier: str
    exposure: str
    numbers: dict[str, Any]
    note: bool


class MissingProfilesError(RuntimeError):
    """The document store holds no profile text, so no company can be mapped for the demand."""


def flow_memo(name: str, demand: str, urls: Sequence[str], settings: FlowSettings, deps: FlowDeps) -> FlowSummary:
    """The memo of one demand: its sources, axes, company map, the numbers of each company and the file.

    The flow is saved first, so a failure of the axes or the map leaves the row and its documents behind.
    """
    flow_row = FlowRow(name, demand, list(urls), prompt_version(deps.prompts), deps.llm.primary.model)
    flow_id = deps.flows.save_flow(flow_row)
    owner = OWNER.format(flow_id=flow_id)
    query = settings.search_prompt.format(name=name, demand=demand)
    searches_left = _gather(query, urls, owner, settings, deps)
    axes = _axes(name, demand, owner, settings, deps)
    deps.flows.record_axes(flow_id, axes)
    companies, rows = _companies(_hits(demand, settings, deps), settings, deps)
    deps.flows.record_companies(flow_id, rows)
    memo_path = _write_memo(name, demand, axes, companies, settings)
    unknown = [row.axis for row in axes if _axis_value(row) == F.UNKNOWN]
    return FlowSummary(flow_id, memo_path, unknown, [line.ticker for line in companies], searches_left)


def company_numbers(
    ticker: str, row: dict[str, Any], peers: Peers, momentum: dict[str, Any], per_max: float
) -> dict[str, Any]:
    """The numbers of one mapped company: its screen row, its sector comparison and its momentum.

    An item the run record does not hold is ``None``. A PER at or above ``per_max`` marks the company as
    overvalued, while a missing PER (a loss, say) never does.
    """
    per = _number(row.get(PER))
    return {
        "stage1_pass": row.get(STAGE1_PASS),
        "fail_rule": row.get(FAIL_RULE),
        "improvement_class": row.get(F.IMPROVEMENT_CLASS),
        "sector_comparison": compare(ticker, row, peers),
        "position": momentum.get("position"),
        "per": per,
        "overvalued": per is not None and per >= per_max,
    }


def render_flow_memo(name: str, demand: str, axes: list[AxisRow], companies: list[CompanyLine]) -> str:
    """The memo of one demand as Markdown: each axis with its quotes, the company table and the note."""
    lines = [f"# {name}", "", f"- 需要: {demand}", "", "## 軸", ""]
    for row in axes:
        lines += _axis_lines(row)
    lines += ["## 恩恵企業", "", *_table_lines(companies), ""]
    lines += _overvalued_lines(companies)
    if any(company.note for company in companies):
        lines += [f"注記: {NOTE}", ""]
    return "\n".join(lines)


def _number(value: Any) -> int | float | None:
    """The value when it is a finite number (a bool and NaN are not), else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value if math.isfinite(value) else None


def _text(value: Any) -> str:
    """The value as text (a bool as ○/×), or ``fields.UNKNOWN`` when the record holds nothing."""
    if isinstance(value, bool):
        return "○" if value else "×"
    return F.UNKNOWN if value is None or value == "" else str(value)


def _axis_value(row: AxisRow) -> str:
    """The answer of one axis, or ``fields.UNKNOWN`` when the run left it empty."""
    value = row.answer.get("value") if isinstance(row.answer, dict) else None
    return F.UNKNOWN if value is None or value == "" else str(value)


def _axis_lines(row: AxisRow) -> list[str]:
    """One axis: its answer, then the quotes of the documents that support it."""
    quotes = [claim["quote"] for claim in row.evidence if claim.get("quote")]
    return [f"### {row.axis}", "", _axis_value(row), ""] + [f"> {quote}" for quote in quotes] + [""]


def _comparison(comparison: Any) -> str:
    """The cells of a ``sector.compare`` result: each metric as value / sector median (ratio)."""
    metrics = comparison.get("metrics") if isinstance(comparison, dict) else None
    if not isinstance(metrics, dict):
        return ""
    return "; ".join(
        f"{metric} {_text(item.get('value'))} / {_text(item.get('median'))} (x{_text(item.get('ratio'))})"
        for metric, item in metrics.items()
        if isinstance(item, dict)
    )


def _cells(company: CompanyLine) -> list[str]:
    """The cells of one company, in the order of ``COLUMNS``."""
    numbers = company.numbers
    comparison = numbers.get("sector_comparison")
    sector = comparison.get("sector") if isinstance(comparison, dict) else None
    return [
        company.ticker,
        company.name,
        company.tier,
        company.exposure,
        _text(sector),
        _text(numbers.get("improvement_class")),
        _text(numbers.get("stage1_pass")),
        _text(numbers.get("fail_rule")),
        _text(numbers.get("position")),
        _text(numbers.get("per")),
        _comparison(comparison),
    ]


def _table_lines(companies: list[CompanyLine]) -> list[str]:
    """The company table, one row per mapped company."""
    header = "| " + " | ".join(COLUMNS) + " |"
    rule = "|" + "---|" * len(COLUMNS)
    return [header, rule] + ["| " + " | ".join(_cells(company)) + " |" for company in companies]


def _overvalued_lines(companies: list[CompanyLine]) -> list[str]:
    """The companies whose PER is at or above the cap, apart from the table, or nothing when none is."""
    flagged = [company for company in companies if company.numbers.get("overvalued")]
    if not flagged:
        return []
    items = [f"- {c.ticker} {c.name}（PER {_text(c.numbers.get('per'))}）" for c in flagged]
    return [f"## {PER_MARK}", "", *items, ""]


def _gather(query: str, urls: Sequence[str], owner: str, settings: FlowSettings, deps: FlowDeps) -> int | None:
    """Fetch the caller's urls and the first cited sources; ``0`` left when the search quota is gone."""
    try:
        deps.throttles.search.acquire()
        answer = deps.search.search(query)
    except QuotaExceeded:
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
    return [AxisRow(axis, {"value": result.answer.get(axis)}, result.evidence, ratio) for axis in settings.axes]


def _hits(demand: str, settings: FlowSettings, deps: FlowDeps) -> list[CompanyHit]:
    """The confirmed companies of the demand; without any profile text there is nothing to rank."""
    if not deps.store.profiles():
        raise MissingProfilesError("the document store holds no profile text; run `main.py profiles` first")
    return build_map(demand, settings.map, MapDeps(deps.llm, deps.prompts, deps.store)).hits


def _companies(
    hits: list[CompanyHit], settings: FlowSettings, deps: FlowDeps
) -> tuple[list[CompanyLine], list[CompanyRow]]:
    """One line and one row per mapped company: its screen row, its sector comparison and its momentum."""
    run_id = deps.records.resolve_run(None)
    metrics = deps.records.run_metrics(run_id)
    tickers = list(metrics)
    peers = Peers(
        sector_medians(metrics, deps.sectors, list(settings.sector_metrics), settings.min_peers),
        deps.sectors,
        list(settings.sector_metrics),
        tuple(tickers),
    )
    universe = Universe(deps.history, tickers, deps.sectors)
    today = datetime.date.today()
    lines: list[CompanyLine] = []
    rows: list[CompanyRow] = []
    for hit in hits:
        row = deps.records.screen_row(run_id, hit.ticker)
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


def _write_memo(
    name: str, demand: str, axes: list[AxisRow], companies: list[CompanyLine], settings: FlowSettings
) -> Path:
    """Write the rendered memo to ``flow.memo_dir`` as ``<name>-<today>.md`` and return its path."""
    settings.memo_dir.mkdir(parents=True, exist_ok=True)
    path = settings.memo_dir / f"{name}-{datetime.date.today():%Y-%m-%d}.md"
    path.write_text(render_flow_memo(name, demand, axes, companies), encoding="utf-8")
    return path
