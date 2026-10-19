"""Map of beneficiary companies: search terms made from the demand, a ranking over the profile texts of the
listed companies, then an LLM confirmation of the top companies. The confirmation reuses ``research.run_task``,
so a mapped company is always backed by a quote of its own documents."""

import json
from dataclasses import dataclass
from typing import Any

from . import fields as F
from .docstore import EDINET, DocStore
from .llm import LLMClient, LLMError
from .research import RETRY, ReplyError, run_task
from .verify import normalize

TERMS = "terms"  # the JSON item of the reply, and the user prompt that asks for the terms
TERMS_SYSTEM = "terms_system"
CONFIRM_TASK = "confirm"
SELLS, TIER, EXPOSURE = "sells", "tier", "exposure"
CONFIRM_FIELDS = [SELLS, TIER, EXPOSURE]
TIERS = ("1次", "2次", "3次以上")
MIN_TERMS = 1


@dataclass(frozen=True)
class MapSettings:
    max_terms: int
    top_k: int
    max_doc_chars: int
    sections: tuple[str, ...]  # the report sections that say what a company sells; the ranking reads only these

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "MapSettings":
        """``flow.map`` and ``flow.max_doc_chars`` (the same cut as the review)."""
        flow = cfg["flow"]
        return cls(
            flow["map"]["max_terms"], flow["map"]["top_k"], flow["max_doc_chars"], tuple(flow["map"]["sections"])
        )


@dataclass(frozen=True)
class MapDeps:
    llm: LLMClient
    prompts: dict[str, str]
    store: DocStore


@dataclass(frozen=True)
class CompanyHit:
    ticker: str
    tier: str
    exposure: str
    evidence: list[dict[str, str]]
    verified_ratio: float


@dataclass(frozen=True)
class MapResult:
    terms: list[str]
    ranked: list[tuple[str, int]]
    hits: list[CompanyHit]
    failed: list[str]  # tickers whose confirmation raised an LLM or reply error


def search_terms(demand: str, settings: MapSettings, deps: MapDeps) -> list[str]:
    """1..``max_terms`` non-empty search phrases for the demand.

    No claims: a search term is made up from the demand and cannot be quoted from a document, so the shared
    ``system``/``user`` prompts (where quotes are mandatory) are not used.
    """
    messages = [
        {"role": "system", "content": deps.prompts[TERMS_SYSTEM]},
        {"role": "user", "content": deps.prompts[TERMS].format(demand=demand, max_terms=settings.max_terms)},
    ]
    reply = deps.llm.chat(messages, json_mode=True)
    try:
        return _parse_terms(reply.text, settings.max_terms)
    except ReplyError as e:
        messages += [
            {"role": "assistant", "content": reply.text},
            {"role": "user", "content": deps.prompts[RETRY].format(error=e)},
        ]
        return _parse_terms(deps.llm.chat(messages, json_mode=True).text, settings.max_terms)


def rank_companies(terms: list[str], profiles: dict[str, str], limit: int) -> list[tuple[str, int]]:
    """Tickers whose profile text holds the most search terms (ties by ticker), at most ``limit``.

    A term counts once however often it appears; a company that holds no term is not ranked. Terms are
    normalized like the profiles, so a half-width term matches full-width text and the other way around, and a
    middle dot is ignored (a report writes サイバー・セキュリティ where the term says サイバーセキュリティ).
    """
    wanted = [term for term in (_key(term) for term in terms) if term]
    normalized = {ticker: _key(text) for ticker, text in profiles.items()}
    counted = [(ticker, sum(1 for term in wanted if term in text)) for ticker, text in normalized.items()]
    ranked = sorted((pair for pair in counted if pair[1]), key=lambda pair: (-pair[1], pair[0]))
    return ranked[:limit]


def _key(text: str) -> str:
    return normalize(text).replace("・", "")


def build_map(demand: str, settings: MapSettings, deps: MapDeps) -> MapResult:
    """Search terms, the ranking over every profile text, then the top ``top_k`` companies confirmed by quotes."""
    terms = search_terms(demand, settings, deps)
    ranked = rank_companies(terms, deps.store.profiles(settings.sections), settings.top_k)
    hits, failed = [], []
    for ticker, _matched in ranked:
        try:
            hit = _confirm(ticker, demand, settings, deps)
        except (LLMError, ReplyError):
            failed.append(ticker)
            continue
        if hit is not None:
            hits.append(hit)
    return MapResult(terms, ranked, hits, failed)


def _confirm(ticker: str, demand: str, settings: MapSettings, deps: MapDeps) -> CompanyHit | None:
    """The company as a hit when ``sells`` is verified true, else ``None``."""
    docs = {
        doc.doc_id: doc.text[: settings.max_doc_chars] for doc in deps.store.documents(ticker) if doc.source == EDINET
    }
    context = {"ticker": ticker, "demand": demand}
    result = run_task(deps.llm, deps.prompts, (CONFIRM_TASK, CONFIRM_FIELDS), docs, context)
    if result.answer[SELLS] is not True:
        return None
    tier = result.answer[TIER]
    return CompanyHit(
        ticker=ticker,
        tier=tier if tier in TIERS else F.UNKNOWN,
        exposure=result.answer[EXPOSURE],
        evidence=result.evidence,
        verified_ratio=len(result.evidence) / result.claims if result.claims else 0.0,
    )


def _parse_terms(text: str, max_terms: int) -> list[str]:
    """The ``terms`` of the reply, checked to be 1..``max_terms`` non-empty strings; else ``ReplyError``."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ReplyError(f"the reply is not valid JSON ({e})") from e
    terms = data.get(TERMS) if isinstance(data, dict) else None
    if not isinstance(terms, list) or not all(isinstance(t, str) and t.strip() for t in terms):
        raise ReplyError(f"the reply must hold {MIN_TERMS} to {max_terms} non-empty terms")
    if not MIN_TERMS <= len(terms) <= max_terms:
        raise ReplyError(f"the reply must hold {MIN_TERMS} to {max_terms} terms, got {len(terms)}")
    return [term.strip() for term in terms]
