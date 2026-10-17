"""The `review` flow: per candidate, documents -> tasks T1..T5 with verified quotes -> a record. A failing ticker is
recorded with its status and the flow goes on."""

from dataclasses import dataclass, field
from typing import Any

from tqdm import tqdm

from . import fields as F
from .docstore import DocStore
from .llm import LLMClient, LLMError
from .records import RecordStore, ReviewRow
from .research import ReplyError, run_task

VERIFIED_ANSWERS = "verified_answers"  # context key: what the last task sees of the tasks before it
SUGGESTION = ("T5", "suggestion")  # (task, answer item) copied to the columns of the same name
SOURCE_TYPE = ("T1", "source_type")
REASON_FORGOTTEN = ("T4", "reason_forgotten")


@dataclass(frozen=True)
class ReviewSettings:
    max_tickers: int
    min_verified_ratio: float
    max_doc_chars: int
    prompt_version: str
    task_fields: dict[str, list[str]]  # in running order
    context_metrics: list[str]

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "ReviewSettings":
        rev = cfg["review"]
        return cls(
            rev["max_tickers"],
            rev["min_verified_ratio"],
            rev["max_doc_chars"],
            rev["prompt_version"],
            rev["tasks"],
            rev["context_metrics"],
        )


@dataclass(frozen=True)
class ReviewSummary:
    reviewed: int
    failed: int
    needs_attention: int


@dataclass(frozen=True)
class ReviewDeps:
    llm: LLMClient
    prompts: dict[str, str]
    records: RecordStore
    store: DocStore


def review_candidates(
    run_id: str,
    candidates: list[tuple[str, dict[str, Any]]],
    tickers: list[str] | None,
    settings: ReviewSettings,
    deps: ReviewDeps,
) -> ReviewSummary:
    """Review the given ``tickers``, else the not yet reviewed ``candidates`` (best ``Priority_Rank`` first, capped)."""
    metrics = dict(candidates)
    if tickers is None:
        done = deps.records.reviewed(run_id)
        todo = sorted((c for c in candidates if c[0] not in done), key=lambda c: c[1][F.PRIORITY_RANK])
        targets = todo[: settings.max_tickers]
    else:
        targets = [(t, metrics.get(t, {})) for t in tickers]
    rows = []
    for ticker, ticker_metrics in tqdm(targets):
        row = _review_ticker(ticker, ticker_metrics, settings, deps)
        deps.records.record_review(run_id, row)
        rows.append(row)
    failed = sum(r.status != F.ReviewStatus.OK for r in rows)
    return ReviewSummary(len(rows) - failed, failed, sum(r.needs_attention for r in rows))


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


def _to_row(ticker: str, out: _Outcome, doc_ids: list[str], settings: ReviewSettings) -> ReviewRow:
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
        doc_ids,
        sorted(set(out.providers)),
        settings.prompt_version,
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
    docs = {d.doc_id: d.text[: settings.max_doc_chars] for d in deps.store.documents(ticker)}
    out = _Outcome(F.ReviewStatus.NO_DOCUMENTS if not docs else F.ReviewStatus.OK)
    if docs:
        context = {"ticker": ticker, "name": metrics.get(F.NAME, "")}
        context |= {m: metrics[m] for m in settings.context_metrics if m in metrics}
        _run_tasks(out, docs, context, settings, deps)
    return _to_row(ticker, out, list(docs), settings)
