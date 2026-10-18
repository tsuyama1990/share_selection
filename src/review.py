"""The `review` flow: per candidate, documents -> tasks T1..T5 with verified quotes -> a record. A failing ticker is
recorded with its status and the flow goes on."""

import datetime
import functools
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from tqdm import tqdm

from . import fields as F
from .cache import StockCache
from .docstore import DocStore
from .llm import LLMClient, LLMError
from .memo import render_memo
from .research import ReplyError, load_prompts, prompt_version, run_task
from .review_store import ReviewRow, ReviewStore
from .sector import MomentumSettings, Peers, Universe, compare, momentum, momentum_note

VERIFIED_ANSWERS = "verified_answers"  # context key: what the last task sees of the tasks before it
SUGGESTION = ("T5", "suggestion")  # (task, answer item) copied to the columns of the same name
SOURCE_TYPE = ("T1", "source_type")
REASON_FORGOTTEN = ("T4", "reason_forgotten")


@dataclass(frozen=True)
class ReviewSettings:
    max_tickers: int
    min_verified_ratio: float
    max_doc_chars: int
    task_fields: dict[str, list[str]]  # in running order
    context_metrics: list[str]
    sources: list[str]  # document sources the tasks may use ("edinet", "web")
    memo_filename: str  # memo file name template, filled with run_id and ticker

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "ReviewSettings":
        rev = cfg["review"]
        return cls(
            rev["max_tickers"],
            rev["min_verified_ratio"],
            rev["max_doc_chars"],
            rev["tasks"],
            rev["context_metrics"],
            rev["sources"],
            cfg["memo"]["filename"],
        )


@dataclass(frozen=True)
class ReviewSummary:
    reviewed: int
    failed: int
    needs_attention: int


def _close_history(cache: StockCache) -> Callable[[str], pd.Series]:
    @functools.cache  # every candidate reads the whole universe; load each ticker once per run
    def history(ticker: str) -> pd.Series:
        data = cache.get(ticker)
        if data is None or data.history.empty or "Close" not in data.history:
            return pd.Series(dtype=float)
        return data.history["Close"].dropna()

    return history


@dataclass(frozen=True)
class ReviewDeps:
    llm: LLMClient
    prompts: dict[str, str]
    reviews: ReviewStore
    store: DocStore
    peers: Peers | None  # sector comparison of each reviewed ticker
    memo_dir: Path | None  # where a memo per reviewed ticker is written
    universe: Universe | None = None  # daily closes of the run's tickers (industry momentum)
    momentum_settings: MomentumSettings | None = None

    @classmethod
    def from_config(
        cls, cfg: dict[str, Any], root: Path, env: Mapping[str, str], stack: ExitStack, peers: Peers | None
    ) -> "ReviewDeps":
        """Open the LLM client and the stores on ``stack``; a missing LLM key raises before any store is opened.

        With ``peers`` the reviews get a sector comparison and a memo in ``memo.dir``; without, neither (the eval).
        """
        http = stack.enter_context(httpx.Client(timeout=cfg["llm"]["timeout_s"]))
        llm = LLMClient.from_config(cfg, http, env)
        prompts = load_prompts(root / cfg["review"]["prompt_dir"])
        reviews = stack.enter_context(ReviewStore.from_config(cfg, root))
        memo_dir = root / cfg["memo"]["dir"] if peers is not None else None
        universe: Universe | None = None
        momentum_settings: MomentumSettings | None = None
        if peers is not None:
            cache = stack.enter_context(StockCache.from_config(cfg, root))
            universe = Universe(_close_history(cache), peers.tickers, peers.sectors)
            momentum_settings = MomentumSettings.from_config(cfg)
        store = stack.enter_context(DocStore.from_config(cfg, root))
        return cls(llm, prompts, reviews, store, peers, memo_dir, universe, momentum_settings)


def review_candidates(
    run_id: str,
    candidates: list[tuple[str, dict[str, Any]]],
    tickers: list[str] | None,
    settings: ReviewSettings,
    deps: ReviewDeps,
) -> ReviewSummary:
    """Review the given ``tickers``, else the not yet reviewed ``candidates`` (given best first; capped)."""
    metrics = dict(candidates)
    if tickers is None:
        done = deps.reviews.reviewed(run_id)
        targets = [c for c in candidates if c[0] not in done][: settings.max_tickers]
    else:
        targets = [(t, metrics.get(t, {})) for t in tickers]
    rows = [_process(run_id, ticker, ticker_metrics, settings, deps) for ticker, ticker_metrics in tqdm(targets)]
    failed = sum(r.status != F.ReviewStatus.OK for r in rows)
    return ReviewSummary(len(rows) - failed, failed, sum(r.needs_attention for r in rows))


def _process(
    run_id: str, ticker: str, metrics: dict[str, Any], settings: ReviewSettings, deps: ReviewDeps
) -> ReviewRow:
    """Review one ticker, record it with its sector comparison and write its memo."""
    row = _review_ticker(ticker, metrics, settings, deps)
    if deps.peers is not None:
        comparison = compare(ticker, metrics, deps.peers)
        if deps.universe is not None and deps.momentum_settings is not None:
            mom = momentum(deps.universe, ticker, deps.momentum_settings, datetime.date.today())
            mom["note"] = momentum_note(mom, deps.momentum_settings)
            comparison["momentum"] = mom
        row = replace(row, sector_comparison=comparison)
    deps.reviews.record_review(run_id, row)
    if deps.memo_dir and row.status == F.ReviewStatus.OK:
        sources = {d.doc_id: d.source_ref for d in deps.store.documents(ticker) if d.doc_id in row.doc_ids}
        memo = render_memo(ticker, metrics.get(F.NAME, ""), asdict(row), row.sector_comparison, sources)
        deps.memo_dir.mkdir(parents=True, exist_ok=True)
        (deps.memo_dir / settings.memo_filename.format(run_id=run_id, ticker=ticker)).write_text(memo, encoding="utf-8")
    return row


def _answer(answers: dict[str, dict[str, Any]], where: tuple[str, str]) -> str | None:
    value = answers.get(where[0], {}).get(where[1])
    return None if value is None else str(value)


@dataclass
class _Outcome:
    status: F.ReviewStatus = F.ReviewStatus.OK
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    claims: int = 0
    providers: list[str] = field(default_factory=list)


def _to_row(ticker: str, out: _Outcome, doc_ids: list[str], settings: ReviewSettings, version: str) -> ReviewRow:
    verified = sum(map(len, out.evidence.values()))
    ratio = verified / out.claims if out.claims else 0.0  # over all claims of the ticker (L2 C4 §5)
    return ReviewRow(
        ticker,
        out.status,
        _answer(out.answers, SUGGESTION),
        _answer(out.answers, SOURCE_TYPE),
        _answer(out.answers, REASON_FORGOTTEN),
        out.answers,
        out.evidence,
        ratio,
        out.status == F.ReviewStatus.OK and ratio < settings.min_verified_ratio,
        None,
        doc_ids,
        sorted(set(out.providers)),
        version,
    )


def _run_tasks(
    out: _Outcome, docs: dict[str, str], context: dict[str, Any], settings: ReviewSettings, deps: ReviewDeps
) -> None:
    """Run T1..Tn into ``out``; the last task also sees the verified answers of the others."""
    last = list(settings.task_fields)[-1]
    try:
        for task_fields in settings.task_fields.items():
            task = task_fields[0]
            task_context = {**context, VERIFIED_ANSWERS: out.answers} if task == last else context
            result = run_task(deps.llm, deps.prompts, task_fields, docs, task_context)
            out.answers[task], out.evidence[task] = result.answer, result.evidence
            out.claims += result.claims
            out.providers += result.providers
    except LLMError:
        out.status = F.ReviewStatus.LLM_FAILED
    except ReplyError:
        out.status = F.ReviewStatus.BAD_JSON


def _review_ticker(ticker: str, metrics: dict[str, Any], settings: ReviewSettings, deps: ReviewDeps) -> ReviewRow:
    docs = {
        d.doc_id: d.text[: settings.max_doc_chars] for d in deps.store.documents(ticker) if d.source in settings.sources
    }
    out = _Outcome(F.ReviewStatus.NO_DOCUMENTS if not docs else F.ReviewStatus.OK)
    if docs:
        context = {"ticker": ticker, "name": metrics.get(F.NAME, "")}
        context |= {m: metrics[m] for m in settings.context_metrics if m in metrics}
        _run_tasks(out, docs, context, settings, deps)
    return _to_row(ticker, out, list(docs), settings, prompt_version(deps.prompts))
