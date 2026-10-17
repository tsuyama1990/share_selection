from src.memo import render_memo

REVIEW = {
    "suggestion": "採用",
    "needs_attention": False,
    "verified_ratio": 0.9,
    "answers": {
        "T1": {"source_type": "P2 値上げ", "tier": "unknown"},
        "T5": {"suggestion": "採用"},
    },
    "evidence": {
        "T1": [{"field": "source_type", "claim": "c", "quote": "値上げの効果が大きい", "doc_id": "edinet:1.T:X"}],
        "T5": [],
    },
}
SOURCES = {"edinet:1.T:X": "S100ABC:BusinessRisks"}
COMPARISON = {"sector": "水産", "metrics": {"PBR": {"value": 0.8, "median": 1.0, "ratio": 0.8}}}


def test_the_memo_has_the_heading_the_suggestion_and_each_task():
    memo = render_memo("1.T", "会社1", REVIEW, None, SOURCES)
    assert memo.startswith("# 1.T 会社1\n")
    assert "提案: 採用" in memo and "### T1" in memo and "### T5" in memo


def test_answers_carry_their_quote_and_source():
    memo = render_memo("1.T", "会社1", REVIEW, None, SOURCES)
    assert "- **source_type**: P2 値上げ" in memo
    assert "「値上げの効果が大きい」 (S100ABC:BusinessRisks)" in memo


def test_a_quote_of_an_unlisted_document_shows_its_doc_id():
    assert "(edinet:1.T:X)" in render_memo("1.T", "会社1", REVIEW, None, {})


def test_unknown_items_are_listed_together_without_a_value():
    memo = render_memo("1.T", "会社1", REVIEW, None, SOURCES)
    assert "- unknown: tier" in memo and "**tier**" not in memo


def test_needs_attention_is_shown_only_when_set():
    assert "要注意" not in render_memo("1.T", "会社1", REVIEW, None, SOURCES)
    memo = render_memo("1.T", "会社1", {**REVIEW, "needs_attention": True}, None, SOURCES)
    assert "**要注意**" in memo and "0.90" in memo


def test_the_peer_table_is_present_only_with_a_comparison_and_shows_missing_as_a_dash():
    assert "同業比較" not in render_memo("1.T", "会社1", REVIEW, None, SOURCES)
    memo = render_memo("1.T", "会社1", REVIEW, COMPARISON, SOURCES)
    assert "## 同業比較 (水産)" in memo and "| PBR | 0.80 | 1.00 | 0.80 |" in memo
    gap = {"sector": "水産", "metrics": {"PBR": {"value": 0.8, "median": None, "ratio": None}}}
    assert "| PBR | 0.80 | - | - |" in render_memo("1.T", "会社1", REVIEW, gap, SOURCES)
