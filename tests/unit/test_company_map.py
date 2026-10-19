"""U-company_map-1..4 (L3 3.1): the search terms, the ranking over the profile texts and the confirmed map."""

import datetime
import json

import pytest

from src import fields as F
from src.company_map import MapDeps, MapSettings, build_map, rank_companies, search_terms
from src.docstore import DocStore, Document
from src.llm import LLMError, Reply
from src.research import ReplyError

WHEN = datetime.datetime(2026, 10, 18, 9, 0)
DEMAND = "生成AIの普及でデータセンターの電力需要が増える"
SETTINGS = MapSettings(max_terms=3, top_k=3, max_doc_chars=2000, sections=("Biz",))
PROMPTS = {
    "system": "Every claim needs a quote of a document.",
    "user": "documents {documents} context {context} task {task}",
    "retry": "The reply was rejected: {error}. Reply again.",
    "terms_system": "List search terms for the demand.",
    "terms": "Demand: {demand}. Give 1 to {max_terms} terms.",
    "confirm": "Confirm the company {ticker} for the demand {demand}.",
}


class FakeLLM:
    """``chat`` returns the given replies in order (an exception in the list is raised); every call is kept."""

    def __init__(self, *replies: str | Exception):
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []
        self.json_modes: list[bool] = []

    def chat(self, messages: list[dict[str, str]], json_mode: bool = False) -> Reply:
        self.calls.append([dict(message) for message in messages])
        self.json_modes.append(json_mode)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Reply(reply, "fake", "fake-model")


@pytest.fixture()
def store(tmp_path):
    with DocStore(tmp_path / "documents.duckdb") as opened:
        yield opened


def put(store, doc_id, ticker, text, source="edinet"):
    store.put(Document(doc_id, ticker, source, f"ref-{doc_id}", "title", WHEN, text))


def claim(field: str, quote: str, doc_id: str) -> dict[str, str]:
    return {"field": field, "claim": f"{field} の主張", "quote": quote, "doc_id": doc_id}


def reply(sells: bool, tier: str, exposure: str, claims: list[dict[str, str]]) -> str:
    answer = {"sells": sells, "tier": tier, "exposure": exposure}
    return json.dumps({"answer": answer, "claims": claims, "unknown": []}, ensure_ascii=False)


def test_rank_companies_normalizes_and_counts_terms():
    profiles = {"1301": "水産 ＡＢＣ 食品", "1302": "食品 食品 冷凍", "1303": "造船", "1304": "食品"}
    assert rank_companies(["食品", "ABC"], profiles, 3) == [("1301", 2), ("1302", 1), ("1304", 1)]


def test_rank_companies_limits_and_drops_unmatched():
    profiles = {"1301": "食品", "1302": "造船", "1303": "冷凍食品"}
    assert rank_companies(["食品"], profiles, 1) == [("1301", 1)]
    assert rank_companies(["航空"], profiles, 5) == []
    assert rank_companies(["  "], profiles, 5) == []


def test_search_terms_uses_the_terms_prompts(store):
    llm = FakeLLM('{"terms": ["データセンター", "半導体"]}')
    assert search_terms(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store)) == ["データセンター", "半導体"]
    assert len(llm.calls) == 1
    assert llm.json_modes == [True]
    system, user = llm.calls[0]
    assert system == {"role": "system", "content": PROMPTS["terms_system"]}
    assert user["role"] == "user"
    assert DEMAND in user["content"]
    assert str(SETTINGS.max_terms) in user["content"]


def test_search_terms_reasks_once_with_the_error(store):
    llm = FakeLLM('{"terms": []}', '{"terms": ["半導体"]}')
    assert search_terms(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store)) == ["半導体"]
    first, second = llm.calls
    assert second[:2] == first
    assert second[2] == {"role": "assistant", "content": '{"terms": []}'}
    assert second[3]["role"] == "user"
    assert "1 to 3" in second[3]["content"]


def test_search_terms_gives_up_after_the_second_bad_reply(store):
    llm = FakeLLM("no json", '{"terms": ["a", "b", "c", "d"]}')
    with pytest.raises(ReplyError):
        search_terms(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store))
    assert len(llm.calls) == 2


def test_search_terms_rejects_a_term_that_is_not_a_string(store):
    llm = FakeLLM('{"terms": [1, "半導体"]}', '{"terms": ["半導体"]}')
    assert search_terms(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store)) == ["半導体"]
    assert len(llm.calls) == 2


def test_map_settings_from_config():
    cfg = {"flow": {"max_doc_chars": 5000, "map": {"max_terms": 8, "top_k": 3, "sections": ["Biz", "Seg"]}}}
    assert MapSettings.from_config(cfg) == MapSettings(
        max_terms=8, top_k=3, max_doc_chars=5000, sections=("Biz", "Seg")
    )


TEXT_1301 = "当社はデータセンターの運営を手がけている。電源は扱っていない。"
TEXT_1302 = "当社は冷凍食品を販売している。"
TEXT_1303 = (
    "当社は電源ユニットと食品包装材を販売している。同社は2次のサプライヤーにあたる。電源事業が売上の3割を占める。"
)


def test_build_map_keeps_only_verified_sellers(store):
    put(store, "edinet:1301:Biz", "1301", TEXT_1301)
    put(store, "edinet:1302:Biz", "1302", TEXT_1302)
    put(store, "edinet:1303:Biz", "1303", TEXT_1303)
    put(store, "WEB-1301", "1301", "当社は電源ユニットを販売している。", source="web")
    put(store, "WEB-1302", "1302", "電源市場の記事。", source="web")
    llm = FakeLLM(
        '{"terms": ["電源", "食品"]}',
        reply(
            True,
            "2次",
            "売上の3割",
            [
                claim("sells", "電源ユニットと食品包装材を販売している", "edinet:1303:Biz"),
                claim("tier", "2次のサプライヤーにあたる", "edinet:1303:Biz"),
                claim("exposure", "売上の3割", "edinet:1303:Biz"),
            ],
        ),
        reply(True, "1次", "不明", [claim("sells", "電源ユニットを販売している", "WEB-1301")]),
        reply(False, "不明", "不明", [claim("sells", "冷凍食品を販売している", "edinet:1302:Biz")]),
    )

    result = build_map(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store))

    assert result.terms == ["電源", "食品"]
    assert result.ranked == [("1303", 2), ("1301", 1), ("1302", 1)]
    assert [hit.ticker for hit in result.hits] == ["1303"]
    assert result.hits[0].tier == "2次"
    assert result.hits[0].exposure == "売上の3割"
    assert [e["field"] for e in result.hits[0].evidence] == ["sells", "tier", "exposure"]
    assert result.hits[0].verified_ratio == 1.0
    assert len(llm.calls) == 1 + SETTINGS.top_k
    confirms = [call[-1]["content"] for call in llm.calls[1:]]
    assert "edinet:1303:Biz" in confirms[0]
    assert "edinet:1301:Biz" not in confirms[0]
    assert all("WEB-" not in content for content in confirms)


def test_build_map_maps_an_unknown_tier_and_exposure(store):
    put(store, "edinet:1301:Biz", "1301", "当社は電源を販売している。")
    llm = FakeLLM(
        '{"terms": ["電源"]}',
        reply(
            True,
            "4次",
            "不明",
            [
                claim("sells", "電源を販売している", "edinet:1301:Biz"),
                claim("tier", "電源を販売している", "edinet:1301:Biz"),
            ],
        ),
    )

    result = build_map(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store))

    assert [hit.ticker for hit in result.hits] == ["1301"]
    assert result.hits[0].tier == F.UNKNOWN
    assert result.hits[0].exposure == F.UNKNOWN


def test_build_map_skips_a_failed_call(store):
    put(store, "edinet:1301:Biz", "1301", "当社は電源を販売している。")
    put(store, "edinet:1302:Biz", "1302", "当社は電源を販売している。")
    llm = FakeLLM(
        '{"terms": ["電源"]}',
        LLMError("all LLM providers failed"),
        reply(True, "1次", "大半", [claim("sells", "電源を販売している", "edinet:1302:Biz")]),
    )

    result = build_map(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store))

    assert result.ranked == [("1301", 1), ("1302", 1)]
    assert [hit.ticker for hit in result.hits] == ["1302"]
    assert result.failed == ["1301"]
    assert len(llm.calls) == 3


def test_build_map_skips_a_reply_that_stays_invalid(store):
    put(store, "edinet:1301:Biz", "1301", "当社は電源を販売している。")
    llm = FakeLLM('{"terms": ["電源"]}', "no json", "still no json")

    result = build_map(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store))

    assert result.ranked == [("1301", 1)]
    assert result.hits == []
    assert result.failed == ["1301"]
    assert len(llm.calls) == 3


def test_build_map_ranks_on_the_given_sections_only(store):
    """A risk section names the demand for almost every company, so it must not rank one (live check 2026-10-18)."""
    put(store, "edinet:1301:Risk", "1301", "サイバー攻撃で電源が止まるリスクがある。")
    put(store, "edinet:1301:Biz", "1301", "当社は冷凍食品を販売している。")
    put(store, "edinet:1302:Biz", "1302", "当社は電源を販売している。")
    sells = [claim("sells", "電源を販売している", "edinet:1302:Biz")]
    llm = FakeLLM('{"terms": ["電源"]}', reply(True, "1次", "不明", sells))

    result = build_map(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store))

    assert result.ranked == [("1302", 1)]
    assert [hit.ticker for hit in result.hits] == ["1302"]
    assert result.failed == []
