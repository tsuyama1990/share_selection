import json
import os

import httpx
import pytest

import main
from src.llm import GeminiSearch, LLMClient, LLMError, Provider
from src.throttle import RateLimiter

OK_BODY = {"choices": [{"message": {"content": "hello"}}]}
MSGS = [{"role": "user", "content": "hi"}]


def providers(*names: str, keys: dict[str, str] | None = None) -> list[Provider]:
    keys = keys or {}
    return [Provider(n, f"https://{n}.test/v1", f"{n}-model", keys.get(n, "k")) for n in names]


def client(handler, provs: list[Provider], max_calls: int = 100) -> LLMClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return LLMClient(provs, http, 0, RateLimiter(max_calls, 60, sleep=lambda _: None))


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
    ],
)
def test_falls_back_to_next_provider(failure):
    handler, calls = recording({"a": failure, "b": httpx.Response(200, json=OK_BODY)})
    reply = client(handler, providers("a", "b")).chat(MSGS)
    assert (reply.text, reply.provider, reply.model) == ("hello", "b", "b-model")
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
    assert "a: LLMError HTTP 429" in str(exc.value)


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
    monkeypatch.setitem(main.COMMANDS, "llm-check", lambda cfg, args: None)
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
    monkeypatch.setattr(main.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET")
    cfg = main.load_config()
    for name in ("GROQ_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    main.cmd_llm_check(cfg, None)
    out = capsys.readouterr().out
    assert "chat: gemini / gemini-2.5-flash, answer 5 chars" in out
    assert "search: answer 11 chars, 2 sources, 2 queries" in out
    assert "SECRET" not in out
