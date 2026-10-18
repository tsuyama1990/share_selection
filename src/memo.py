"""The Markdown research memo of one reviewed ticker."""

from typing import Any

from . import fields as F

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
        lines.append("先に上がった会社はその後負けやすい（有意ではない）")
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
