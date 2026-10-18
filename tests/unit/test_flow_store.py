"""U-flow_store-1・2: the flow records of `flow-memo` (decisions are out of scope here)."""

import pytest

from src import flow_store
from src.flow_store import AxisRow, CompanyRow, FlowRow, FlowStore

CFG = {"flow": {"db_file": "flow.duckdb"}}


@pytest.fixture
def store(tmp_path):
    with FlowStore(tmp_path / "flow.duckdb") as store:
        yield store


def _flow() -> FlowRow:
    return FlowRow("半導体", "生成AIの需要", ["https://example.com/a"], "v1", "deepseek")


def _axes() -> list[AxisRow]:
    return [
        AxisRow("demand_wave", {"demand_wave": "拡大"}, [{"doc_id": "d1", "quote": "需要は拡大している"}], 1.0),
        AxisRow("ceiling", {}, [], 0.0),
    ]


def _companies() -> list[CompanyRow]:
    return [
        CompanyRow(
            "6501",
            "1次",
            "3割",
            [{"doc_id": "d2", "quote": "受注が増えた"}],
            "run-1",
            True,
            None,
            {"psr": 2.5, "pbr": 3.1},
            4,
        ),
        CompanyRow("7011", "2次", "不明", [], "run-1", False, "psr", {}, None),
    ]


def _count(store, table):
    return store.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _columns(store, table):
    """Column name and DuckDB type, in the order of the table (`rowid` is virtual, not part of the schema)."""
    rows = store.con.execute(f"DESCRIBE {table}").fetchall()
    return [(name, dtype) for name, dtype, *_ in rows if name != "rowid"]


def test_recording_the_same_rows_twice_adds_no_rows(store):
    flow_id = store.save_flow(_flow())
    store.record_axes(flow_id, _axes())
    store.record_companies(flow_id, _companies())
    assert store.save_flow(_flow()) == flow_id
    store.record_axes(flow_id, _axes())
    store.record_companies(flow_id, _companies())
    assert _count(store, "flows") == 1
    assert _count(store, "flow_axes") == len(_axes())
    assert _count(store, "flow_companies") == len(_companies())


def test_written_rows_are_read_back_with_their_json_columns(store):
    flow_id = store.save_flow(_flow())
    store.record_axes(flow_id, _axes())
    store.record_companies(flow_id, _companies())
    axes = sorted(store.axes(flow_id), key=lambda row: row.axis)
    companies = sorted(store.companies(flow_id), key=lambda row: row.ticker)
    assert axes == sorted(_axes(), key=lambda row: row.axis)
    assert companies == sorted(_companies(), key=lambda row: row.ticker)


def test_only_the_flow_asked_for_is_returned(store):
    first = store.save_flow(_flow())
    other = store.save_flow(FlowRow("電力", "データセンターの新設", [], "v1", "deepseek"))
    store.record_axes(first, _axes())
    store.record_axes(other, [AxisRow("demand_wave", {"demand_wave": "縮小"}, [], 0.5)])
    assert other != first
    assert store.axes(other) == [AxisRow("demand_wave", {"demand_wave": "縮小"}, [], 0.5)]
    assert len(store.axes(first)) == 2
    assert store.companies(first) == []


def test_schema_columns_are_in_the_dataclass_order(store):
    assert _columns(store, "flows") == [
        ("flow_id", "VARCHAR"),
        ("name", "VARCHAR"),
        ("demand", "VARCHAR"),
        ("urls", "JSON"),
        ("prompt_version", "VARCHAR"),
        ("llm_provider", "VARCHAR"),
        ("created_at", "TIMESTAMP"),
    ]
    assert _columns(store, "flow_axes") == [
        ("flow_id", "VARCHAR"),
        ("axis", "VARCHAR"),
        ("answer", "JSON"),
        ("evidence", "JSON"),
        ("verified_ratio", "DOUBLE"),
    ]
    assert _columns(store, "flow_companies") == [
        ("flow_id", "VARCHAR"),
        ("ticker", "VARCHAR"),
        ("tier", "VARCHAR"),
        ("exposure", "VARCHAR"),
        ("evidence", "JSON"),
        ("run_id", "VARCHAR"),
        ("stage1_pass", "BOOLEAN"),
        ("fail_rule", "VARCHAR"),
        ("valuations", "JSON"),
        ("past3m_rank", "INTEGER"),
    ]


def test_from_config_opens_flow_db_file_under_root(tmp_path):
    with FlowStore.from_config(CFG, tmp_path) as store:
        store.save_flow(_flow())
    assert (tmp_path / "flow.duckdb").exists()


@pytest.mark.xfail(
    strict=True, reason="U-flow_store-2, 3: `DecisionRow`, `OutcomeRow` and `due_decisions` come with flow-decide"
)
def test_due_decisions_exists():
    assert all(hasattr(flow_store, name) for name in ("DecisionRow", "OutcomeRow", "due_decisions"))
