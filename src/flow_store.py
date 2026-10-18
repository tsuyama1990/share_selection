"""The flow records of ``flow-memo`` (their own DuckDB file, ``flow.db_file``).

A flow, its axes and the company map are written here, so a memo can be rendered again without new LLM calls.
Decisions (``flow-decide``) and their outcomes (``evaluate``) are kept here too.
"""

import datetime
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS flows (
        flow_id TEXT, name TEXT, demand TEXT, urls JSON, prompt_version TEXT, llm_provider TEXT,
        created_at TIMESTAMP, PRIMARY KEY (flow_id))""",
    """CREATE TABLE IF NOT EXISTS flow_axes (
        flow_id TEXT, axis TEXT, answer JSON, evidence JSON, verified_ratio DOUBLE,
        PRIMARY KEY (flow_id, axis))""",
    """CREATE TABLE IF NOT EXISTS flow_companies (
        flow_id TEXT, ticker TEXT, tier TEXT, exposure TEXT, evidence JSON, run_id TEXT,
        stage1_pass BOOLEAN, fail_rule TEXT, valuations JSON, past3m_rank INTEGER,
        PRIMARY KEY (flow_id, ticker))""",
    """CREATE TABLE IF NOT EXISTS flow_decisions (
        flow_id TEXT, ticker TEXT, decided_at TIMESTAMP, action TEXT, reason TEXT, max_yen BIGINT,
        PRIMARY KEY (flow_id, ticker, decided_at))""",
    """CREATE TABLE IF NOT EXISTS flow_outcomes (
        flow_id TEXT, ticker TEXT, decided_at TIMESTAMP, months INTEGER, excess DOUBLE, control_excess DOUBLE,
        control_n INTEGER, PRIMARY KEY (flow_id, ticker, decided_at, months))""",
)


@dataclass(frozen=True)
class FlowRow:
    name: str
    demand: str
    urls: list[str]
    prompt_version: str
    llm_provider: str


@dataclass(frozen=True)
class AxisRow:
    axis: str
    answer: dict[str, Any]
    evidence: list[dict[str, str]]  # the claims that support the answer
    verified_ratio: float


@dataclass(frozen=True)
class CompanyRow:
    ticker: str
    tier: str  # 1次・2次・3次以上・不明
    exposure: str
    evidence: list[dict[str, str]]
    run_id: str
    stage1_pass: bool
    fail_rule: str | None
    valuations: dict[str, Any]
    past3m_rank: int | None


@dataclass(frozen=True)
class DecisionRow:
    flow_id: str
    ticker: str
    decided_at: datetime.datetime
    action: str  # buy or skip
    reason: str
    max_yen: int | None  # None: no cap


@dataclass(frozen=True)
class OutcomeRow:
    flow_id: str
    ticker: str
    decided_at: datetime.datetime
    months: int
    excess: float | None  # against the equal-weight mean of the scored tickers
    control_excess: float | None
    control_n: int


def _flow_id(row: FlowRow) -> str:
    """Today plus a digest of the name and demand: a retry of the same run overwrites it, a new run does not."""
    digest = hashlib.blake2s(f"{row.name}\n{row.demand}".encode()).hexdigest()[:8]
    return f"{datetime.date.today():%Y%m%d}-{digest}"


def _company_row(values: tuple[Any, ...]) -> CompanyRow:
    ticker, tier, exposure, evidence, run_id, passed, fail_rule, valuations, rank = values
    return CompanyRow(
        ticker, tier, exposure, json.loads(evidence), run_id, passed, fail_rule, json.loads(valuations), rank
    )


class FlowStore:
    """Flows, their axes and the company map in ``db_path``; writing the same key twice replaces the row."""

    def __init__(self, db_path: Path):
        self.con = duckdb.connect(str(db_path))
        for ddl in SCHEMA:
            self.con.execute(ddl)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], root: Path) -> "FlowStore":
        """Open ``flow.db_file`` resolved from ``root``."""
        return cls(root / cfg["flow"]["db_file"])

    def __enter__(self) -> "FlowStore":
        return self

    def __exit__(self, *_exc) -> None:
        self.con.close()

    def save_flow(self, row: FlowRow) -> str:
        """Store the flow and return its id; saving the same flow again (a retry) replaces it."""
        flow_id = _flow_id(row)
        self.con.execute(
            "INSERT OR REPLACE INTO flows VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                flow_id,
                row.name,
                row.demand,
                json.dumps(row.urls, ensure_ascii=False),
                row.prompt_version,
                row.llm_provider,
                datetime.datetime.now(),
            ],
        )
        return flow_id

    def record_axes(self, flow_id: str, rows: list[AxisRow]) -> None:
        """Store the axes of the flow, replacing an axis recorded earlier under the same name."""
        for row in rows:
            self.con.execute(
                "INSERT OR REPLACE INTO flow_axes VALUES (?, ?, ?, ?, ?)",
                [
                    flow_id,
                    row.axis,
                    json.dumps(row.answer, ensure_ascii=False),
                    json.dumps(row.evidence, ensure_ascii=False),
                    row.verified_ratio,
                ],
            )

    def record_companies(self, flow_id: str, rows: list[CompanyRow]) -> None:
        """Store the company map of the flow, replacing a company recorded earlier for the same ticker."""
        for row in rows:
            self.con.execute(
                "INSERT OR REPLACE INTO flow_companies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    flow_id,
                    row.ticker,
                    row.tier,
                    row.exposure,
                    json.dumps(row.evidence, ensure_ascii=False),
                    row.run_id,
                    row.stage1_pass,
                    row.fail_rule,
                    json.dumps(row.valuations, ensure_ascii=False),
                    row.past3m_rank,
                ],
            )

    def axes(self, flow_id: str) -> list[AxisRow]:
        """The axes recorded for the flow."""
        sql = "SELECT axis, answer, evidence, verified_ratio FROM flow_axes WHERE flow_id = ?"
        return [
            AxisRow(axis, json.loads(answer), json.loads(evidence), ratio)
            for axis, answer, evidence, ratio in self.con.execute(sql, [flow_id]).fetchall()
        ]

    def companies(self, flow_id: str) -> list[CompanyRow]:
        """The company map recorded for the flow."""
        sql = (
            "SELECT ticker, tier, exposure, evidence, run_id, stage1_pass, fail_rule, valuations, past3m_rank"
            " FROM flow_companies WHERE flow_id = ?"
        )
        return [_company_row(values) for values in self.con.execute(sql, [flow_id]).fetchall()]

    def record_decision(self, row: DecisionRow) -> None:
        """Store a decision; deciding the same company again at another time adds a row."""
        self.con.execute(
            "INSERT OR REPLACE INTO flow_decisions VALUES (?, ?, ?, ?, ?, ?)",
            [row.flow_id, row.ticker, row.decided_at, row.action, row.reason, row.max_yen],
        )

    def record_outcome(self, row: OutcomeRow) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO flow_outcomes VALUES (?, ?, ?, ?, ?, ?, ?)",
            [row.flow_id, row.ticker, row.decided_at, row.months, row.excess, row.control_excess, row.control_n],
        )

    def due_decisions(self, months: int, today: datetime.date) -> list[DecisionRow]:
        """Decisions at least ``months`` old on ``today`` without an outcome for that horizon yet."""
        rows = self.con.execute(
            """SELECT d.flow_id, d.ticker, d.decided_at, d.action, d.reason, d.max_yen FROM flow_decisions d
               WHERE NOT EXISTS (SELECT 1 FROM flow_outcomes o WHERE o.flow_id = d.flow_id AND o.ticker = d.ticker
                                 AND o.decided_at = d.decided_at AND o.months = ?)
               ORDER BY d.decided_at, d.flow_id, d.ticker""",
            [months],
        ).fetchall()
        due = [DecisionRow(*r) for r in rows]
        return [r for r in due if _months_after(r.decided_at.date(), months) <= today]


def _months_after(day: datetime.date, months: int) -> datetime.date:
    """The same day ``months`` later, or the month's last day when it has fewer days."""
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    for d in range(day.day, 0, -1):
        try:
            return datetime.date(year, month, d)
        except ValueError:
            continue
    raise ValueError(day)
