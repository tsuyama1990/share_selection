"""Design gate: docs/architecture/L1_architecture.md must agree with src/ and tests/e2e/.

Rules (L1 section 9): modules listed in section 3 match src/ one to one; every requirement is traced to an E2E or a
gate in section 8; every E2E in section 7 has a test file (a not-yet-implemented one must be strict xfail);
no open-decision section remains.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "architecture" / "L1_architecture.md"
NOT_BUILT = ("🆕", "⏸")
OPEN_DECISIONS_TITLE = "決めていただきたいこと"


def section(number: int) -> list[str]:
    """Lines of the '## <number>.' section of the L1 document."""
    lines = DOC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## {number}."))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def table_rows(lines: list[str]) -> list[list[str]]:
    """Cells of each table row whose first cell is an ID such as R1, N5, C3 or E2."""
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines if line.startswith("|")]
    return [r for r in rows if re.fullmatch(r"[A-Z]\d+", r[0])]


def test_section3_modules_match_src():
    rows = table_rows(section(3))
    listed: dict[str, str] = {}
    for row in rows:
        for name in re.findall(r"`([\w]+\.py)`", " ".join(row)):
            listed[name] = " ".join(row)
    actual = {p.name for p in (ROOT / "src").glob("*.py") if p.name != "__init__.py"}
    missing_in_doc = sorted(actual - set(listed))
    assert not missing_in_doc, f"src modules not listed in L1 section 3: {missing_in_doc}"
    absent = [
        f"{name} (row: {row[:40]}...)"
        for name, row in listed.items()
        if not (ROOT / "src" / name).exists()
        and not (ROOT / name).exists()
        and not any(mark in row for mark in NOT_BUILT)
    ]
    assert not absent, f"L1 section 3 lists modules that do not exist and are not marked 🆕 or ⏸: {absent}"


def requirement_ids() -> list[str]:
    return [r[0] for r in table_rows(section(1)) if re.fullmatch(r"[RN]\d+", r[0])]


def test_section8_traces_every_requirement():
    ids = requirement_ids()
    assert ids, "no requirement IDs (R*/N*) found in L1 section 1"
    traced = {r[0]: r[-1] for r in table_rows(section(8))}
    untraced = [i for i in ids if i not in traced]
    assert not untraced, f"requirements without a row in L1 section 8: {untraced}"
    no_proof = [i for i in ids if not re.search(r"E\d+", traced[i]) and "ゲート" not in traced[i]]
    assert not no_proof, f"requirements in section 8 with neither an E-id nor ゲート: {no_proof}"
    defined = {r[0] for r in table_rows(section(7))}
    undefined = sorted({e for i in ids for e in re.findall(r"E\d+", traced[i])} - defined)
    assert not undefined, f"E-ids used in section 8 but not defined in section 7: {undefined}"


def e2e_files(number: str) -> list[Path]:
    return sorted((ROOT / "tests" / "e2e").glob(f"test_{number.lower()}_*.py"))


def is_strict_xfail(decorator: ast.expr) -> bool:
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "xfail"
        and any(k.arg == "strict" and getattr(k.value, "value", None) is True for k in decorator.keywords)
    )


def test_section7_every_e2e_has_a_test_file():
    problems = []
    for row in table_rows(section(7)):
        e_id, status = row[0], row[-1]
        files = e2e_files(e_id)
        if not files:
            problems.append(f"{e_id}: no tests/e2e/test_{e_id.lower()}_*.py")
        elif "🆕" in status:
            for path in files:
                body = ast.parse(path.read_text(encoding="utf-8")).body
                tests = [n for n in body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
                plain = [t.name for t in tests if not any(is_strict_xfail(d) for d in t.decorator_list)]
                if plain or not tests:
                    problems.append(f"{e_id} is 🆕 but {path.name} has tests that are not strict xfail: {plain}")
    assert not problems, "L1 section 7 vs tests/e2e: " + "; ".join(problems)


def test_no_open_decisions_section():
    titles = [line for line in DOC.read_text(encoding="utf-8").splitlines() if line.startswith("#")]
    open_titles = [t for t in titles if OPEN_DECISIONS_TITLE in t]
    assert not open_titles, f"resolve or defer (with a reason) the open decisions: {open_titles}"
