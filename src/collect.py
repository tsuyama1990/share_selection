"""The `docs` flow: EDINET index and annual reports, then web sources of a Gemini search per candidate."""

import datetime
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

import httpx
from tqdm import tqdm

from . import fields as F
from .docstore import DocStore
from .edinet import EdinetClient, fetch_annual_report, update_index
from .llm import SECONDS_PER_MINUTE, GeminiSearch, LLMError, QuotaExceeded
from .throttle import RateLimiter
from .tickers import TICKER_SUFFIX
from .webfetch import fetch_document


@dataclass(frozen=True)
class CollectSettings:
    index_days: int
    doc_type_code: str
    sections: list[str]
    search_prompt: str
    max_sources: int
    max_bytes: int

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "CollectSettings":
        ed, web, docs = cfg["edinet"], cfg["webfetch"], cfg["docs"]
        return cls(
            ed["index_days"],
            ed["doc_type_code"],
            ed["sections"],
            docs["search_prompt"],
            docs["max_sources"],
            web["max_bytes"],
        )


@dataclass(frozen=True)
class CollectSummary:
    edinet_docs: int
    edinet_failed: int
    web_docs: int
    searches_left: int  # candidates not searched because the search quota ran out


@dataclass(frozen=True)
class CollectClients:
    """Clients of the flow; ``search`` is None when ``docs.search`` is off (then no web documents are collected)."""

    edinet: EdinetClient
    search: GeminiSearch | None
    web_http: httpx.Client
    search_limiter: RateLimiter
    fetch_limiter: RateLimiter

    @classmethod
    def from_config(cls, cfg: dict[str, Any], env: Mapping[str, str], stack: ExitStack) -> "CollectClients":
        """Open the HTTP clients on ``stack``; a missing API key raises before any record is read."""
        llm, web = cfg["llm"], cfg["webfetch"]
        edinet_http = stack.enter_context(httpx.Client(timeout=cfg["edinet"]["timeout_s"]))
        edinet = EdinetClient.from_config(cfg, edinet_http, env)
        search = None
        if cfg["docs"]["search"]:
            search = GeminiSearch.from_config(cfg, stack.enter_context(httpx.Client(timeout=llm["timeout_s"])), env)
        headers = {"User-Agent": web["user_agent"]}
        web_http = stack.enter_context(httpx.Client(timeout=web["timeout_s"], headers=headers))
        search_limiter = RateLimiter(llm["max_calls_per_minute"], SECONDS_PER_MINUTE)
        return cls(edinet, search, web_http, search_limiter, RateLimiter(1, web["request_interval_s"]))


def collect_documents(
    candidates: list[tuple[str, dict]],
    settings: CollectSettings,
    clients: CollectClients,
    store: DocStore,
    today: datetime.date,
) -> CollectSummary:
    """EDINET sections of every candidate; then, if searching, web sources of the candidates without web documents.

    Searches go in ``Priority_Rank`` order and stop at the search quota.
    """
    update_index(clients.edinet, store, today, settings.index_days)
    stored = [
        fetch_annual_report(clients.edinet, store, t, settings.doc_type_code, settings.sections)
        for t, _ in tqdm(candidates)
    ]
    web_docs, searches_left = _collect_web(candidates, settings, clients, store)
    return CollectSummary(sum(map(len, stored)), sum(not ids for ids in stored), web_docs, searches_left)


def _collect_web(
    candidates: list[tuple[str, dict]], settings: CollectSettings, clients: CollectClients, store: DocStore
) -> tuple[int, int]:
    """(documents stored, candidates left unsearched)."""
    if clients.search is None:
        return 0, 0
    pending = sorted((c for c in candidates if not store.has_source(c[0], "web")), key=lambda c: c[1][F.PRIORITY_RANK])
    stored = 0
    for done, (ticker, metrics) in enumerate(tqdm(pending)):
        clients.search_limiter.acquire()
        prompt = settings.search_prompt.format(name=metrics[F.NAME], code=ticker.removesuffix(TICKER_SUFFIX))
        try:
            answer = clients.search.search(prompt)
        except QuotaExceeded as e:
            store.record_error(ticker, "web", "search", str(e))
            return stored, len(pending) - done
        except LLMError as e:
            store.record_error(ticker, "web", "search", str(e))
            continue
        for _, uri in answer.sources[: settings.max_sources]:
            clients.fetch_limiter.acquire()
            stored += fetch_document(uri, ticker, clients.web_http, store, settings.max_bytes) is not None
    return stored, 0
