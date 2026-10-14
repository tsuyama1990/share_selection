"""Code budget: the source size may only grow by an explicit, reviewed decision."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SLACK = 10


def _source_lines() -> int:
    files = [*sorted((ROOT / "src").rglob("*.py")), ROOT / "main.py"]
    lines = (line.strip() for f in files for line in f.read_text(encoding="utf-8").splitlines())
    return sum(1 for line in lines if line and not line.startswith("#"))


def _budget() -> int:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["code_budget"]["max_source_lines"]


def test_source_is_within_budget():
    actual, budget = _source_lines(), _budget()
    assert actual <= budget, (
        f"over budget: {actual} > {budget}. Delete code or raise budget "
        "with a Budget-Increase: line in the commit message"
    )


def test_budget_is_not_stale():
    actual, budget = _source_lines(), _budget()
    assert actual >= budget - SLACK, f"budget is stale: lower max_source_lines to {actual} (currently {budget})"
