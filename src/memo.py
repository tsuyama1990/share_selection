"""The Markdown research memo of one reviewed ticker."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from . import fields as F
from .flow_store import AxisRow

PER = "PER"  # the trailing PER of the cache, shown as it is (not a report column)
PER_MARK = "超割高"
COLUMNS = ("コード", "名前", "何次", "売上比率", "業種", "改善区分", "通過", "落ちた条件", "位置", "PER", "比較")
NOTE = "先に上がった会社はその後負けやすい（有意ではない）"

ATTENTION = "要注意"


def _number(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _task_lines(task: str, answer: dict[str, Any], claims: list[dict[str, str]], sources: dict[str, str]) -> list[str]:
    lines = [f"### {task}"]
    for item, value in answer.items():
        if value != F.UNKNOWN:
            lines.append(f"- **{item}**: {value}")
            lines += [
                f"  - 「{c['quote']}」 ({sources.get(c['doc_id'], c['doc_id'])})" for c in claims if c["field"] == item
            ]
    unknown = [item for item, value in answer.items() if value == F.UNKNOWN]
    return lines + ([f"- unknown: {', '.join(unknown)}"] if unknown else [])


def _peers_table(comparison: dict[str, Any]) -> list[str]:
    lines = [f"## 同業比較 ({comparison['sector']})", "", "| 指標 | 値 | 業種の中央値 | 比 |", "|---|---|---|---|"]
    for metric, c in comparison["metrics"].items():
        lines.append(f"| {metric} | {_number(c['value'])} | {_number(c['median'])} | {_number(c['ratio'])} |")
    return lines


def _momentum_lines(momentum: dict[str, Any]) -> list[str]:
    excess = momentum.get("industry_excess")
    rank = momentum.get("industry_rank")
    industries = momentum.get("industries")
    position = momentum.get("position")
    excess_text = "-" if excess is None else f"{excess:+.2%}"
    rank_text = "-" if rank is None or not industries else f"{rank} / {industries}"
    position_text = "-" if position is None else f"{position:.1f}"
    lines = [
        "",
        f"業種の勢い（{momentum.get('months')} か月）: 超過リターン {excess_text}、"
        f"全業種の中の順位 {rank_text}、業種の中の位置 {position_text}",
    ]
    if momentum.get("note"):
        lines.append(NOTE)
    return lines


def render_memo(
    ticker: str, name: str, review: dict[str, Any], comparison: dict[str, Any] | None, sources: dict[str, str]
) -> str:
    """Markdown: suggestion, verified answers with their quotes and sources, unknown items, the peer table."""
    lines = [f"# {ticker} {name}", "", f"提案: {review['suggestion']}"]
    if review["needs_attention"]:
        lines += ["", f"**{ATTENTION}**: 引用の照合率 {review['verified_ratio']:.2f} が下限未満"]
    lines += ["", "## 調査"]
    for task, answer in review["answers"].items():
        lines += ["", *_task_lines(task, answer, review["evidence"][task], sources)]
    if comparison:
        lines += ["", *_peers_table(comparison)]
        if comparison.get("momentum"):
            lines += _momentum_lines(comparison["momentum"])
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class CompanyLine:
    ticker: str
    name: str
    tier: str
    exposure: str
    numbers: dict[str, Any]
    note: bool


def render_flow_memo(
    name: str, demand: str, axes: list[AxisRow], companies: list[CompanyLine], terms: Sequence[str] = ()
) -> str:
    """The memo of one demand as Markdown: each axis with its quotes, the company table and the note.

    ``terms`` are the words the company map searched for; they change between runs, so the memo shows them.
    """
    lines = [f"# {name}", "", f"- 需要: {demand}", f"- 地図の検索語: {'、'.join(terms) or F.UNKNOWN}", "", "## 軸", ""]
    for row in axes:
        quotes = [claim["quote"] for claim in row.evidence if claim.get("quote")]
        lines += [f"### {row.axis}", "", axis_value(row), ""] + [f"> {quote}" for quote in quotes] + [""]
    lines += ["## 恩恵企業", "", *_table_lines(companies), ""]
    lines += _overvalued_lines(companies)
    if any(company.note for company in companies):
        lines += [f"注記: {NOTE}", ""]
    return "\n".join(lines)


def _text(value: Any) -> str:
    """The value as text (a bool as ○/×), or ``fields.UNKNOWN`` when the record holds nothing."""
    if isinstance(value, bool):
        return "○" if value else "×"
    if isinstance(value, float):
        return f"{value:.2f}"
    return F.UNKNOWN if value is None or value == "" else str(value)


def axis_value(row: AxisRow) -> str:
    """The answer of one axis, or ``fields.UNKNOWN`` when the run left it empty."""
    value = row.answer.get("value") if isinstance(row.answer, dict) else None
    return F.UNKNOWN if value is None or value == "" else str(value)


def _comparison(comparison: Any) -> str:
    """The cells of a ``sector.compare`` result: each metric as value / sector median (ratio)."""
    metrics = comparison.get("metrics") if isinstance(comparison, dict) else None
    if not isinstance(metrics, dict):
        return ""
    return "; ".join(
        f"{metric} {_text(item.get('value'))} / {_text(item.get('median'))} (x{_text(item.get('ratio'))})"
        for metric, item in metrics.items()
        if isinstance(item, dict)
    )


def _cells(company: CompanyLine) -> list[str]:
    """The cells of one company, in the order of ``COLUMNS``."""
    numbers = company.numbers
    comparison = numbers.get("sector_comparison")
    sector = comparison.get("sector") if isinstance(comparison, dict) else None
    return [
        company.ticker,
        company.name,
        company.tier,
        company.exposure,
        _text(sector),
        _text(numbers.get("improvement_class")),
        _text(numbers.get("stage1_pass")),
        _text(numbers.get("fail_rule")),
        _text(numbers.get("position")),
        _text(numbers.get("per")),
        _comparison(comparison),
    ]


def _table_lines(companies: list[CompanyLine]) -> list[str]:
    """The company table, one row per mapped company."""
    header = "| " + " | ".join(COLUMNS) + " |"
    rule = "|" + "---|" * len(COLUMNS)
    listed = [company for company in companies if not company.numbers.get("overvalued")]  # those go apart
    return [header, rule] + ["| " + " | ".join(_cells(company)) + " |" for company in listed]


def _overvalued_lines(companies: list[CompanyLine]) -> list[str]:
    """The companies whose PER is at or above the cap, apart from the table, or nothing when none is."""
    flagged = [company for company in companies if company.numbers.get("overvalued")]
    if not flagged:
        return []
    items = [f"- {c.ticker} {c.name}（PER {_text(c.numbers.get('per'))}）" for c in flagged]
    return [f"## {PER_MARK}", "", *items, ""]
