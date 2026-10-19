"""Unit tests of ``src.flow``: the flow settings, the numbers of one company and the memo text (U-flow-1, 2, 4)."""

import pytest

from src import fields as F
from src import flow
from src.flow import FlowSettings, company_numbers
from src.flow_store import AxisRow
from src.memo import NOTE, CompanyLine, render_flow_memo
from src.sector import Peers, PeerSettings

CFG = {
    "flow": {
        "db_file": "flow.duckdb",
        "memo_dir": "results/flow",
        "prompts_dir": "prompts/flow",
        "search_prompt": "{name} の需要を調べてください: {demand}",
        "max_sources": 5,
        "max_doc_chars": 20000,
        "axes": ["需要の波", "終わりの手がかり", "競合", "値決め", "リスク"],
        "map": {"max_terms": 5, "top_k": 10, "sections": ["Biz"]},
        "per_max": 100,
    },
    "webfetch": {"max_bytes": 20000000},
    "sector": {
        "metrics": ["Real_PSR", "PBR"],
        "min_peers": 5,
        "momentum_months": 3,
        "momentum_note_top_share": 0.334,
        "momentum_note_position": 0.5,
    },
}

ROW = {
    "stage1_pass": True,
    "stage1_fail_rule": None,
    "Improvement_Class": "clear",
    "Real_PSR": 0.8,
    "PBR": 1.2,
    "PER": 15,
}

NUMBERS = {
    "stage1_pass": True,
    "fail_rule": None,
    "improvement_class": "clear",
    "sector_comparison": {
        "sector": "情報・通信業",
        "metrics": {"Real_PSR": {"value": 0.8, "median": 1.0, "ratio": 0.8}},
    },
    "position": 0.25,
    "per": 15,
    "overvalued": False,
}

AXES = [
    AxisRow("需要の波", {"value": "補助金が追い風"}, [{"quote": "補助金の拡充を進める"}], 1.0),
    AxisRow("終わりの手がかり", {"value": F.UNKNOWN}, [], 0.0),
]

COMPANIES = [
    CompanyLine("1301", "サンプル商事", "1次", "30%", NUMBERS, False),
    CompanyLine("1302", "サンプル電機", "2次", F.UNKNOWN, {**NUMBERS, "overvalued": True}, True),
]


def _peers() -> Peers:
    """Two tickers of one sector, so the median and the ratio of ``Real_PSR`` are known."""
    return Peers(
        medians={"情報・通信業": {"Real_PSR": 1.0}},
        sectors={"A": "情報・通信業", "B": "情報・通信業"},
        metrics=["Real_PSR"],
        tickers=("A", "B"),
    )


# U-flow-4: FlowSettings.from_config


def test_flow_settings_resolves_the_directories_from_the_root(tmp_path):
    settings = FlowSettings.from_config(CFG, tmp_path)
    assert settings.memo_dir == tmp_path / "results/flow"
    assert settings.prompts_dir == tmp_path / "prompts/flow"


def test_flow_settings_reads_the_numbers_of_flow_and_sector(tmp_path):
    settings = FlowSettings.from_config(CFG, tmp_path)
    assert settings.max_sources == 5
    assert settings.max_doc_chars == 20000
    assert settings.per_max == 100
    assert settings.axes == ("需要の波", "終わりの手がかり", "競合", "値決め", "リスク")
    assert settings.peers == PeerSettings(("Real_PSR", "PBR"), 5)
    assert settings.momentum.months == 3


def test_flow_settings_takes_max_bytes_from_webfetch_and_the_map_from_flow_map(tmp_path):
    cfg = {**CFG, "webfetch": {"max_bytes": 1000}}
    settings = FlowSettings.from_config(cfg, tmp_path)
    assert settings.max_bytes == 1000
    assert settings.map.max_terms == 5
    assert settings.map.top_k == 10
    assert settings.map.max_doc_chars == 20000


# U-flow-2: company_numbers


def test_company_numbers_keeps_the_recorded_items():
    numbers = company_numbers("A", ROW, _peers(), {"position": 0.25}, 100)
    assert numbers["stage1_pass"] is True
    assert numbers["fail_rule"] is None
    assert numbers["improvement_class"] == "clear"
    assert numbers["sector_comparison"]["sector"] == "情報・通信業"
    assert numbers["sector_comparison"]["metrics"]["Real_PSR"] == {"value": 0.8, "median": 1.0, "ratio": 0.8}
    assert numbers["position"] == 0.25
    assert numbers["per"] == 15
    assert numbers["overvalued"] is False


def test_company_numbers_marks_a_per_at_or_above_the_cap_as_overvalued():
    assert company_numbers("A", {**ROW, "PER": 100}, _peers(), {}, 100)["overvalued"] is True
    assert company_numbers("A", {**ROW, "PER": 120}, _peers(), {}, 100)["overvalued"] is True
    assert company_numbers("A", {**ROW, "PER": 99}, _peers(), {}, 100)["overvalued"] is False


def test_company_numbers_leaves_a_missing_item_null():
    numbers = company_numbers("B", {}, _peers(), {}, 100)
    assert numbers["stage1_pass"] is None
    assert numbers["fail_rule"] is None
    assert numbers["improvement_class"] is None
    assert numbers["position"] is None
    assert numbers["per"] is None
    assert numbers["overvalued"] is False


def test_company_numbers_ignores_a_per_that_is_not_a_number():
    numbers = company_numbers("A", {**ROW, "PER": float("nan")}, _peers(), {}, 100)
    assert numbers["per"] is None
    assert numbers["overvalued"] is False


# U-flow-1: render_flow_memo


def test_render_flow_memo_lists_each_axis_with_its_quotes():
    text = render_flow_memo("半導体", "需要の説明", AXES, [])
    assert "需要の波" in text
    assert "補助金が追い風" in text
    assert "> 補助金の拡充を進める" in text


def test_render_flow_memo_shows_unknown_for_an_axis_without_a_quote():
    text = render_flow_memo("半導体", "需要の説明", [AXES[1]], [])
    assert "終わりの手がかり" in text
    assert F.UNKNOWN in text


def test_render_flow_memo_has_the_company_table():
    text = render_flow_memo("半導体", "需要の説明", [], COMPANIES)
    assert "| コード | 名前 | 何次 | 売上比率 | 業種 |" in text
    assert "| 1301 | サンプル商事 | 1次 | 30% | 情報・通信業 |" in text
    assert "clear" in text
    assert "○" in text


def test_render_flow_memo_lists_an_overvalued_company_apart():
    text = render_flow_memo("半導体", "需要の説明", [], COMPANIES)
    assert "## 超割高" in text
    assert "- 1302 サンプル電機" in text
    assert "| 1302 |" not in text  # not in the company table as well
    quiet = [CompanyLine("1301", "サンプル商事", "1次", "30%", NUMBERS, False)]
    assert "超割高" not in render_flow_memo("半導体", "需要の説明", [], quiet)


def test_render_flow_memo_adds_the_note_only_for_a_flagged_company():
    assert NOTE in render_flow_memo("半導体", "需要の説明", [], COMPANIES)
    quiet = [CompanyLine("1301", "サンプル商事", "1次", "30%", NUMBERS, False)]
    assert NOTE not in render_flow_memo("半導体", "需要の説明", [], quiet)


# U-flow-3: Decision


@pytest.mark.parametrize("action", ["buy", "skip"])
def test_decision_accepts_buy_and_skip_and_keeps_none_apart_from_zero(action):
    assert flow.Decision("f", "1.T", action, "why", None).max_yen is None
    assert flow.Decision("f", "1.T", action, "why", 0).max_yen == 0


@pytest.mark.parametrize(("action", "max_yen"), [("hold", None), ("buy", -1)])
def test_decision_rejects_other_actions_and_negative_caps(action, max_yen):
    with pytest.raises(ValueError):
        flow.Decision("f", "1.T", action, "why", max_yen)


# U-flow-5: flow_decide


class FakeFlows:
    def __init__(self):
        self.rows = []

    def record_decision(self, row):
        self.rows.append(row)


def test_flow_decide_records_the_decision_at_the_minute():
    flows = FakeFlows()
    flow.flow_decide(flow.Decision("f", "1.T", "skip", "too dear", None), flows)  # type: ignore[arg-type]
    row = flows.rows[0]
    assert (row.flow_id, row.ticker, row.action, row.reason, row.max_yen) == ("f", "1.T", "skip", "too dear", None)
    assert row.decided_at.second == 0 and row.decided_at.microsecond == 0
