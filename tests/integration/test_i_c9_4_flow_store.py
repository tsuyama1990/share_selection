"""I-C9-4 (L2 C9 section 7): the flow records of `flow-memo`.

A flow, its axes and the company map are written to `flow.db_file`; recording the same run again adds no rows, and
what was written can be read back after reopening the file. Decisions and their answer check are out of scope.
"""

from src.flow_store import AxisRow, CompanyRow, FlowRow, FlowStore

CFG = {"flow": {"db_file": "flow.duckdb"}}

FLOW = FlowRow(
    name="生成AIの電力需要",
    demand="データセンターの新設で電力の消費が増える",
    urls=["https://example.com/datacenters", "https://example.com/power"],
    prompt_version="ab12cd34",
    llm_provider="deepseek-v4-flash",
)
AXES = [
    AxisRow(
        "demand_wave", {"demand_wave": "拡大が続く"}, [{"doc_id": "web:1", "quote": "電力需要は拡大している"}], 1.0
    ),
    AxisRow("ceiling", {"ceiling": "不明"}, [], 0.0),
]
COMPANIES = [
    CompanyRow(
        "6501",
        "1次",
        "3割",
        [{"doc_id": "edinet:1", "quote": "重電の受注が増えた"}],
        "run-20261018",
        True,
        None,
        {"Real_PSR": 2.5, "PBR": 3.1},
        4,
    ),
    CompanyRow("9501", "2次", "不明", [], "run-20261018", False, "Real_PSR", {}, None),
]


def _count(store, table):
    return store.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_the_same_run_is_recorded_once_and_read_back_after_reopening(tmp_path):
    with FlowStore.from_config(CFG, tmp_path) as store:
        flow_id = store.save_flow(FLOW)
        store.record_axes(flow_id, AXES)
        store.record_companies(flow_id, COMPANIES)
        # A retry of the same run (the same name and demand on the same day) writes the same rows again.
        assert store.save_flow(FLOW) == flow_id
        store.record_axes(flow_id, AXES)
        store.record_companies(flow_id, COMPANIES)
        assert _count(store, "flows") == 1
        assert _count(store, "flow_axes") == len(AXES)
        assert _count(store, "flow_companies") == len(COMPANIES)

    assert (tmp_path / "flow.duckdb").exists()
    with FlowStore.from_config(CFG, tmp_path) as store:
        assert store.axes(flow_id) == AXES or sorted(store.axes(flow_id), key=lambda row: row.axis) == sorted(
            AXES, key=lambda row: row.axis
        )
        assert sorted(store.companies(flow_id), key=lambda row: row.ticker) == sorted(
            COMPANIES, key=lambda row: row.ticker
        )
