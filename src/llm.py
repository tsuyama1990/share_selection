from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import httpx

from .throttle import RateLimiter


class LLMError(RuntimeError):
    pass


class QuotaExceeded(LLMError):
    """HTTP 429. For Gemini search this is the daily free quota of grounded requests (shared by all models)."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True)
class Reply:
    text: str
    provider: str
    model: str


@dataclass(frozen=True)
class SearchAnswer:
    text: str
    queries: list[str]
    sources: list[tuple[str, str]]  # (title, uri)


class LLMClient:
    """OpenAI-compatible chat/completions over ordered providers; the next one is tried on any failure."""

    def __init__(self, providers: list[Provider], http: httpx.Client, temperature: float, limiter: RateLimiter):
        self._providers = [p for p in providers if p.api_key]
        self._http, self._temperature, self._limiter = http, temperature, limiter

    def chat(self, messages: list[dict[str, str]], json_mode: bool = False) -> Reply:
        if not self._providers:
            raise LLMError("no LLM provider has an API key")
        failures = []
        for p in self._providers:
            self._limiter.acquire()
            body: dict[str, Any] = {"model": p.model, "messages": messages, "temperature": self._temperature}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            try:
                resp = self._http.post(
                    f"{p.base_url.rstrip('/')}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {p.api_key}"},
                )
                if resp.is_error:
                    raise LLMError(f"HTTP {resp.status_code}")
                return Reply(resp.json()["choices"][0]["message"]["content"], p.name, p.model)
            except (httpx.TransportError, LLMError, KeyError, IndexError, ValueError) as e:
                failures.append(f"{p.name}: {type(e).__name__} {e}".strip())
        raise LLMError("all LLM providers failed: " + "; ".join(failures))


class GeminiSearch:
    """Gemini native generateContent with the google_search tool (grounded answer with sources)."""

    def __init__(self, base_url: str, model: str, api_key: str, http: httpx.Client):
        self._url, self._api_key, self._http = f"{base_url}/models/{model}:generateContent", api_key, http

    def search(self, prompt: str) -> SearchAnswer:
        if not self._api_key:
            raise LLMError("no API key for Gemini search")
        body = {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]}
        try:
            resp = self._http.post(self._url, json=body, headers={"x-goog-api-key": self._api_key})
        except httpx.TransportError as e:
            raise LLMError(f"Gemini search failed: {type(e).__name__}") from e
        if resp.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise QuotaExceeded(f"Gemini search failed: HTTP {resp.status_code}")
        if resp.is_error:
            raise LLMError(f"Gemini search failed: HTTP {resp.status_code}")
        candidate = resp.json()["candidates"][0]
        text = "".join(part.get("text", "") for part in candidate["content"]["parts"])
        grounding = candidate.get("groundingMetadata", {})
        chunks = grounding.get("groundingChunks", [])
        sources = [(c["web"].get("title", ""), c["web"]["uri"]) for c in chunks if "web" in c]
        return SearchAnswer(text, grounding.get("webSearchQueries", []), sources)
