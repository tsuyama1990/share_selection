import json
import os

import httpx
import pytest

import main
from src.llm import GeminiSearch, LLMClient, LLMError, Provider
from src.throttle import RateLimiter, Retry

OK_BODY = {"choices": [{"message": {"content": "hello"}}]}
MSGS = [{"role": "user", "content": "hi"}]


def providers(*names: str, keys: dict[str, str] | None = None) -> list[Provider]:
    keys = keys or {}
    return [Provider(n, f"https://{n}.test/v1", f"{n}-model", keys.get(n, "k")) for n in names]


def client(
    handler, provs: list[Provider], max_calls: int = 100, retries: int = 0, waits: list | None = None
) -> LLMClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    retry = Retry(retries, 1.0, sleep=(waits if waits is not None else []).append)
    return LLMClient(provs, http, 0, RateLimiter(max_calls, 60, sleep=lambda _: None), retry)


def recording(responses: dict[str, httpx.Response | Exception]):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        r = responses[request.url.host.split(".")[0]]
        if isinstance(r, Exception):
            raise r
        return r

    return handler, calls


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(429),
        httpx.Response(500),
        httpx.Response(402, json={"error": "quota"}),
        httpx.ConnectTimeout("t"),
        httpx.ConnectError("c"),
        httpx.Response(200, json={"unexpected": 1}),
        httpx.Response(200, json={"error": {"code": 502, "message": "Provider returned error"}}),
    ],
)
def test_falls_back_to_next_provider(failure):
    handler, calls = recording({"a": failure, "b": httpx.Response(200, json=OK_BODY)})
    reply = client(handler, providers("a", "b")).chat(MSGS)
    assert (reply.text, reply.provider, reply.model) == ("hello", "b", "b-model")
    assert [c.url.host for c in calls] == ["a.test", "b.test"]


def test_transient_failures_are_retried_on_the_same_provider():
    answers = iter([httpx.Response(503), httpx.ConnectTimeout("t"), httpx.Response(200, json=OK_BODY)])

    def handler(request: httpx.Request) -> httpx.Response:
        r = next(answers)
        if isinstance(r, Exception):
            raise r
        return r

    waits: list[float] = []
    assert client(handler, providers("a", "b"), retries=2, waits=waits).chat(MSGS).provider == "a"
    assert waits == [1.0, 2.0]


def test_other_failures_are_not_retried():
    handler, calls = recording({"a": httpx.Response(402), "b": httpx.Response(200, json=OK_BODY)})
    assert client(handler, providers("a", "b"), retries=2).chat(MSGS).provider == "b"
    assert [c.url.host for c in calls] == ["a.test", "b.test"]


def test_first_provider_answers_without_fallback():
    handler, calls = recording({"a": httpx.Response(200, json=OK_BODY), "b": httpx.Response(500)})
    assert client(handler, providers("a", "b")).chat(MSGS).provider == "a"
    assert len(calls) == 1


def test_skips_providers_with_empty_key():
    handler, calls = recording({"b": httpx.Response(200, json=OK_BODY)})
    reply = client(handler, providers("a", "b", keys={"a": ""})).chat(MSGS)
    assert reply.provider == "b"
    assert [c.url.host for c in calls] == ["b.test"]


def test_all_fail_raises_without_leaking_keys():
    handler, _ = recording({"a": httpx.Response(429), "b": httpx.ConnectTimeout("t")})
    with pytest.raises(LLMError, match="all LLM providers failed") as exc:
        client(handler, providers("a", "b", keys={"a": "SECRET-A", "b": "SECRET-B"})).chat(MSGS)
    assert "SECRET" not in str(exc.value)
    assert "a: HTTP 429" in str(exc.value)


def test_no_keys_raises():
    with pytest.raises(LLMError, match="no LLM provider"):
        client(lambda r: httpx.Response(200), providers("a", keys={"a": ""})).chat(MSGS)


def test_request_body_and_json_option():
    handler, calls = recording({"a": httpx.Response(200, json=OK_BODY)})
    c = client(handler, providers("a", keys={"a": "SECRET"}))
    c.chat(MSGS)
    c.chat(MSGS, json_mode=True)
    plain, as_json = (json.loads(r.content) for r in calls)
    assert plain == {"model": "a-model", "messages": MSGS, "temperature": 0}
    assert as_json["response_format"] == {"type": "json_object"}
    assert calls[0].headers["authorization"] == "Bearer SECRET"
    assert str(calls[0].url) == "https://a.test/v1/chat/completions"


SEARCH_BODY = {
    "candidates": [
        {
            "content": {"parts": [{"text": "answer "}, {"text": "text"}]},
            "groundingMetadata": {
                "webSearchQueries": ["q1", "q2"],
                "groundingChunks": [{"web": {"title": "T1", "uri": "https://u1"}}, {"web": {"uri": "https://u2"}}],
            },
        }
    ]
}


def search(handler, key: str = "SECRET") -> GeminiSearch:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GeminiSearch("https://g.test/v1beta", "m", key, http)


def test_search_parses_answer_queries_and_sources():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=SEARCH_BODY)

    result = search(handler).search("question")
    assert result.text == "answer text"
    assert result.queries == ["q1", "q2"]
    assert result.sources == [("T1", "https://u1"), ("", "https://u2")]
    assert str(seen[0].url) == "https://g.test/v1beta/models/m:generateContent"
    assert json.loads(seen[0].content)["tools"] == [{"google_search": {}}]
    assert "SECRET" not in str(seen[0].url)


def test_search_without_grounding_metadata():
    body = {"candidates": [{"content": {"parts": [{"text": "x"}]}}]}
    result = search(lambda r: httpx.Response(200, json=body)).search("q")
    assert (result.queries, result.sources) == ([], [])


@pytest.mark.parametrize("response", [httpx.Response(429), httpx.ConnectTimeout("t")])
def test_search_failure_raises(response):
    def handler(request):
        if isinstance(response, Exception):
            raise response
        return response

    with pytest.raises(LLMError, match="Gemini search failed"):
        search(handler).search("q")


def test_dotenv_fills_missing_vars_but_keeps_existing(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LLM_TEST_EXISTING=from_file\nLLM_TEST_NEW=from_file\n", encoding="utf-8")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setitem(main.COMMANDS, "llm-check", (lambda cfg, args: None, "test"))
    monkeypatch.setattr("sys.argv", ["main.py", "llm-check"])
    monkeypatch.setenv("LLM_TEST_EXISTING", "from_shell")
    monkeypatch.delenv("LLM_TEST_NEW", raising=False)
    main.main()
    assert os.environ["LLM_TEST_EXISTING"] == "from_shell"
    assert os.environ["LLM_TEST_NEW"] == "from_file"
    monkeypatch.delenv("LLM_TEST_NEW")


def test_llm_check_prints_only_summary(monkeypatch, capsys):
    def handler(request):
        if "generateContent" in request.url.path:
            return httpx.Response(200, json=SEARCH_BODY)
        return httpx.Response(200, json=OK_BODY)

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET")
    cfg = main.load_config()
    for name in ("GROQ_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    main.cmd_llm_check(cfg, None)
    out = capsys.readouterr().out
    assert "chat: gemini-lite / gemini-3.5-flash-lite, answer 5 chars" in out
    assert "search: answer 11 chars, 2 sources, 2 queries" in out
    assert "SECRET" not in out


@pytest.mark.parametrize("content", [None, ""])
def test_an_empty_reply_is_retried_on_the_same_provider(content):
    answers = iter(
        [httpx.Response(200, json={"choices": [{"message": {"content": content}}]}), httpx.Response(200, json=OK_BODY)]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(answers)

    waits: list[float] = []
    assert client(handler, providers("a", "b"), retries=1, waits=waits).chat(MSGS).provider == "a"
    assert waits == [1.0]
