from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import httpx

from .config import MissingKeyError, require_key
from .throttle import RateLimiter, Retry


class LLMError(RuntimeError):
    pass


class _TransientError(LLMError):
    """HTTP 429/5xx or a transport error: worth another attempt on the same provider."""


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
    """OpenAI-compatible chat/completions over ordered providers. A transient failure (HTTP 429/5xx, transport) is
    retried on the same provider; then, or on any other failure, the next provider is tried."""

    def __init__(
        self, providers: list[Provider], http: httpx.Client, temperature: float, limiter: RateLimiter, retry: Retry
    ):
        self._providers = [p for p in providers if p.api_key]
        self._http, self._temperature, self._limiter, self._retry = http, temperature, limiter, retry

    @classmethod
    def from_config(cls, cfg: dict[str, Any], http: httpx.Client, env: Mapping[str, str]) -> "LLMClient":
        """Providers whose key variable is empty are skipped by the client."""
        llm = cfg["llm"]
        providers = [
            Provider(p["name"], p["base_url"], p["model"], env.get(p["key_env"], "")) for p in llm["providers"]
        ]
        limiter = RateLimiter.per_minute(llm["max_calls_per_minute"])
        return cls(providers, http, llm["temperature"], limiter, Retry(llm["retries"], llm["retry_wait_s"]))

    @property
    def primary(self) -> Provider:
        """The first provider that has a key."""
        if not self._providers:
            raise MissingKeyError("set the API key of an LLM provider (environment or .env)")
        return self._providers[0]

    def chat(self, messages: list[dict[str, str]], json_mode: bool = False) -> Reply:
        if not self._providers:
            raise LLMError("no LLM provider has an API key")
        body: dict[str, Any] = {"messages": messages, "temperature": self._temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        failures = []
        for p in self._providers:
            for attempt in range(self._retry.times + 1):
                try:
                    return self._post(p, body)
                except _TransientError as e:
                    failures.append(f"{p.name}: {e}")
                    if attempt < self._retry.times:
                        self._retry.sleep(self._retry.wait_s * (attempt + 1))
                except (LLMError, KeyError, IndexError, ValueError) as e:
                    failures.append(f"{p.name}: {type(e).__name__} {e}".strip())
                    break
        raise LLMError("all LLM providers failed: " + "; ".join(failures))

    def _post(self, p: Provider, body: dict[str, Any]) -> Reply:
        self._limiter.acquire()
        try:
            resp = self._http.post(
                f"{p.base_url.rstrip('/')}/chat/completions",
                json={**body, "model": p.model},
                headers={"Authorization": f"Bearer {p.api_key}"},
            )
        except httpx.TransportError as e:
            raise _TransientError(type(e).__name__) from None
        if resp.status_code == HTTPStatus.TOO_MANY_REQUESTS or resp.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise _TransientError(f"HTTP {resp.status_code}")
        if resp.is_error:
            raise LLMError(f"HTTP {resp.status_code}")
        return Reply(resp.json()["choices"][0]["message"]["content"], p.name, p.model)


class GeminiSearch:
    """Gemini native generateContent with the google_search tool (grounded answer with sources)."""

    def __init__(self, base_url: str, model: str, api_key: str, http: httpx.Client):
        self._url, self._api_key, self._http = f"{base_url}/models/{model}:generateContent", api_key, http

    @classmethod
    def from_config(cls, cfg: dict[str, Any], http: httpx.Client, env: Mapping[str, str]) -> "GeminiSearch":
        search = cfg["llm"]["search"]
        return cls(search["base_url"], search["model"], require_key(env, search["key_env"]), http)

    def search(self, prompt: str) -> SearchAnswer:
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
