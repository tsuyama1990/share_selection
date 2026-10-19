"""I-C9-1 (L3 3.1): the map of beneficiary companies over a temporary DocStore.

The search terms rank the company whose report actually names the demand within top_k; a "sells to" claim that
no quote of the company's own EDINET documents supports is not mapped; web documents are neither ranked nor shown
to the LLM.
"""

import datetime
import json

from src.company_map import MapDeps, MapSettings, build_map
from src.docstore import DocStore, Document
from src.llm import Reply

WHEN = datetime.datetime(2026, 10, 18, 9, 0)
DEMAND = "データセンターの電力需要"
SETTINGS = MapSettings(max_terms=3, top_k=2, max_doc_chars=2000, sections=("Biz",))
PROMPTS = {
    "system": "Every claim needs a quote of a document.",
    "user": "documents {documents} context {context} task {task}",
    "retry": "The reply was rejected: {error}. Reply again.",
    "terms_system": "List search terms for the demand.",
    "terms": "Demand: {demand}. Give 1 to {max_terms} terms.",
    "confirm": "Confirm the company {ticker} for the demand {demand}.",
}
TEXT_1301 = (
    "当社はデータセンター向けの電源ユニットを販売している。"
    "同社は1次のサプライヤーにあたる。電源事業が売上の大半を占める。"
)
TEXT_1301B = "電源事業の拡大を進めている。"
TEXT_1302 = "当社は冷凍食品を販売している。"


class FakeLLM:
    """``chat`` returns the given replies in order; every call is kept."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []
        self.json_modes: list[bool] = []

    def chat(self, messages: list[dict[str, str]], json_mode: bool = False) -> Reply:
        self.calls.append([dict(message) for message in messages])
        self.json_modes.append(json_mode)
        return Reply(self.replies.pop(0), "fake", "fake-model")


def claim(field: str, quote: str, doc_id: str) -> dict[str, str]:
    return {"field": field, "claim": f"{field} の主張", "quote": quote, "doc_id": doc_id}


def reply(sells: bool, tier: str, exposure: str, claims: list[dict[str, str]]) -> str:
    answer = {"sells": sells, "tier": tier, "exposure": exposure}
    return json.dumps({"answer": answer, "claims": claims, "unknown": []}, ensure_ascii=False)


def test_map_of_the_company_documents(tmp_path):
    with DocStore(tmp_path / "documents.duckdb") as store:
        store.put(Document("edinet:1301:Biz", "1301", "edinet", "S100-1301", "有価証券報告書", WHEN, TEXT_1301))
        store.put(Document("edinet:1301B:Biz", "1301", "edinet", "S100-1301B", "有価証券報告書", WHEN, TEXT_1301B))
        store.put(Document("edinet:1302:Biz", "1302", "edinet", "S100-1302", "有価証券報告書", WHEN, TEXT_1302))
        store.put(
            Document("WEB-1302", "1302", "web", "https://example.com/1302", "記事", WHEN, "冷凍食品と電源の市場。")
        )
        assert store.profiles(SETTINGS.sections) == {"1301": f"{TEXT_1301}\n{TEXT_1301B}", "1302": TEXT_1302}

        llm = FakeLLM(
            '{"terms": ["電源", "食品"]}',
            reply(
                True,
                "1次",
                "売上の大半",
                [
                    claim("sells", "データセンター向けの電源ユニットを販売している", "edinet:1301:Biz"),
                    claim("tier", "1次のサプライヤーにあたる", "edinet:1301:Biz"),
                    claim("exposure", "電源事業が売上の大半を占める", "edinet:1301:Biz"),
                ],
            ),
            reply(
                True,
                "3次以上",
                "不明",
                [claim("sells", "冷凍食品と電源の市場", "WEB-1302")],
            ),
        )

        result = build_map(DEMAND, SETTINGS, MapDeps(llm, PROMPTS, store))

        assert result.terms == ["電源", "食品"]
        assert result.ranked == [("1301", 1), ("1302", 1)]
        assert [hit.ticker for hit in result.hits] == ["1301"]
        assert result.hits[0].tier == "1次"
        assert result.hits[0].exposure == "売上の大半"
        assert len(result.hits[0].evidence) == len(PROMPTS) - len(PROMPTS) + 3
        assert len(llm.calls) == 1 + SETTINGS.top_k
        confirms = [call[-1]["content"] for call in llm.calls[1:]]
        assert "edinet:1301:Biz" in confirms[0]
        assert "edinet:1302:Biz" not in confirms[0]
        assert all("WEB-" not in content for content in confirms)
