"""E11: `flow-decide` records the user's decisions and `evaluate` scores only the ones past the horizon.

Mirrors `test_e4_evaluate.py`: prices come from a fake Yahoo client, the record store carries one run recorded
250 days ago, and the decisions are recorded through the CLI 200 days ago (between the 6- and 12-month
horizons), so only the 6-month horizon is scored.
"""

import datetime
from unittest import mock

import pandas as pd

import main
from src import fields as F
from src.flow_store import FlowRow, FlowStore
from src.records import RecordStore, RunInfo
from src.screener import ScreenResult
from tests.fixtures.config import CFG

RUN_AGE_DAYS = 250  # the run is old enough for its 6-month horizon to elapse
DECISION_AGE_DAYS = 200  # between the 6- and 12-month horizons
TICKERS = ("1.T", "2.T", "3.T")
ROW = {F.PBR: 1.0, F.IMPROVEMENT_CLASS: "clear", F.QUALITY_FLAGS: []}
INFO = RunInfo("2026-03", "abc", {}, datetime.date(2026, 1, 1), None, None)


class FakeYahoo:
    @classmethod
    def from_config(cls, _cfg):
        return cls()

    def adjusted_close(self, ticker, start):
        days = pd.bdate_range(start, datetime.date.today())
        slope = {"1.T": 1.0, "2.T": -0.1, "3.T": 0.5, "1306.T": 0.5}.get(ticker, 0.0)
        return pd.Series([100.0 + slope * i for i in range(len(days))], index=days)


def record_old_run(project) -> None:
    run_at = datetime.datetime.now() - datetime.timedelta(days=RUN_AGE_DAYS)
    with RecordStore.from_config(CFG, project.root) as store, mock.patch("src.records.datetime.datetime") as dt:
        dt.now.return_value = run_at
        store.record_run(INFO, {t: ScreenResult(True, None, dict(ROW)) for t in TICKERS})
    rows = "".join(f"{t.removesuffix('.T')},会社{t},業種A\n" for t in TICKERS)
    (project.root / CFG["system"]["input_csv"]).write_text("code,name,sector33\n" + rows, encoding="utf-8")


def test_flow_decide_records_and_evaluate_scores_past_horizons(project, monkeypatch, capsys):
    monkeypatch.setattr(main, "YahooClient", FakeYahoo)
    record_old_run(project)
    with FlowStore.from_config(CFG, project.root) as flows:
        flow_id = flows.save_flow(FlowRow("f", "d", [], "pv", "prov"))

    old = datetime.datetime.now() - datetime.timedelta(days=DECISION_AGE_DAYS)
    with mock.patch("src.flow.datetime.datetime") as dt:
        dt.now.return_value = old
        project.run("flow-decide", "--flow", flow_id, "--ticker", "1.T", "--action", "buy", "--reason", "why")
        project.run("flow-decide", "--flow", flow_id, "--ticker", "2.T", "--action", "skip", "--reason", "no")
    out = capsys.readouterr().out
    assert f"Decision recorded: {flow_id} 1.T buy." in out
    assert f"Decision recorded: {flow_id} 2.T skip." in out

    project.run("evaluate")
    with FlowStore.from_config(CFG, project.root) as flows:
        rows = flows.con.execute("SELECT ticker, months FROM flow_outcomes ORDER BY ticker").fetchall()
    assert [r[:2] for r in rows] == [("1.T", 6), ("2.T", 6)]
