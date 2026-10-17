"""Design gate: docs/architecture/L1_architecture.md must agree with src/ and tests/e2e/.

L2 documents (docs/architecture/L2_*.md) are checked as well: module table state vs src/, integration plan vs
tests/integration/.
L3 documents (L3_*.md): module states agree with L2, public names of built modules match src/, and every
unit test plan target of a built module appears in tests/unit/test_<module>.py.

Rules (L1 section 9): modules listed in section 3 match src/ one to one; every requirement is traced to an E2E or a
gate in section 8; every E2E in section 7 has a test file (a not-yet-implemented one must be strict xfail);
no open-decision section remains; every live scenario LVn of section 7.1 has a test_lv<n>_* in tests/live/.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "architecture" / "L1_architecture.md"
NOT_BUILT = "🆕"
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
        if not (ROOT / "src" / name).exists() and not (ROOT / name).exists() and NOT_BUILT not in row
    ]
    assert not absent, f"L1 section 3 lists modules that do not exist and are not marked 🆕: {absent}"


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


LIVE_ROW = re.compile(r"\|\s*LV(\d+)\s*\|")


def test_section7_every_live_scenario_has_a_test():
    """L1 section 7.1: each live scenario LVn has a test function test_lv<n>_* under tests/live/."""
    ids = [int(m.group(1)) for line in section(7) if (m := LIVE_ROW.match(line))]
    names = {
        node.name
        for path in (ROOT / "tests" / "live").glob("test_*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef)
    }
    missing = [f"LV{n}" for n in ids if not any(name.startswith(f"test_lv{n}_") for name in names)]
    assert ids, "L1 section 7.1 lists no live scenario"
    assert not missing, f"live scenarios without a tests/live/test_*.py function test_lv<n>_*: {missing}"


def test_no_open_decisions_section():
    titles = [line for line in DOC.read_text(encoding="utf-8").splitlines() if line.startswith("#")]
    open_titles = [t for t in titles if OPEN_DECISIONS_TITLE in t]
    assert not open_titles, f"resolve or defer (with a reason) the open decisions: {open_titles}"


L2_DOCS = sorted((ROOT / "docs" / "architecture").glob("L2_*.md"))
INTEGRATION_ID = re.compile(r"I-C(\d+)-(\d+)")


def l2_table(doc: Path, title_part: str) -> list[list[str]]:
    """Rows of the first table in the '## ' section of an L2 document whose title contains title_part."""
    lines = doc.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## ") and title_part in line)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [
        [c.strip() for c in line.strip().strip("|").split("|")] for line in lines[start:end] if line.startswith("|")
    ]


def module_table(doc: Path) -> dict[str, tuple[str, set[str]]]:
    """Module name -> (leading state mark ✅ or 🆕, backticked names in the second cell) from the module table."""
    modules = {}
    for row in l2_table(doc, "モジュール"):
        match = re.match(r"`(\w+\.py)`", row[0])
        if match:
            modules[match.group(1)] = (row[-1][:1], set(re.findall(r"`(\w+)`", row[1])))
    return modules


def test_l2_modules_are_in_l1_and_state_matches_src():
    l1_text = " ".join(" ".join(r) for r in table_rows(section(3)))
    problems = []
    for doc in L2_DOCS:
        for name, (state, _) in module_table(doc).items():
            built = (ROOT / "src" / name).exists()
            if f"`{name}`" not in l1_text:
                problems.append(f"{doc.name}: {name} is not in L1 section 3")
            if state not in ("✅", "🆕"):
                problems.append(f"{doc.name}: {name} has state {state!r}; only ✅ or 🆕 are allowed")
            elif state == "✅" and not built:
                problems.append(f"{doc.name}: {name} is ✅ but src/{name} does not exist")
            elif state == "🆕" and built:
                problems.append(f"{doc.name}: {name} is 🆕 but src/{name} exists; update the state to ✅")
    assert not problems, "L2 module tables: " + "; ".join(problems)


def integration_plan() -> list[tuple[Path, list[str]]]:
    return [
        (doc, row) for doc in L2_DOCS for row in l2_table(doc, "結合テスト計画") if INTEGRATION_ID.fullmatch(row[0])
    ]


def test_l2_integration_ids_are_unique():
    ids = [row[0] for _, row in integration_plan()]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert ids, "no integration test IDs (I-C*-*) found in the L2 documents"
    assert not dup, f"duplicate integration test IDs across L2 documents: {dup}"


def test_l2_integration_plan_matches_tests():
    problems = []
    for doc, row in integration_plan():
        i_id, status = row[0], row[-1]
        c, n = INTEGRATION_ID.fullmatch(i_id).groups()  # type: ignore[union-attr]
        if status.startswith("✅"):
            paths = re.findall(r"`(tests/integration/[\w./*-]+)`", status)
            if not any((ROOT / p).is_file() for p in paths):
                problems.append(f"{doc.name} {i_id} is ✅ but names no existing file under tests/integration/: {paths}")
        elif status.startswith("🆕"):
            files = sorted((ROOT / "tests" / "integration").glob(f"test_i_c{c}_{n}_*.py"))
            if not files:
                problems.append(
                    f"{doc.name} {i_id} is 🆕 but has no tests/integration/test_i_c{c}_{n}_*.py placeholder"
                )
            for path in files:
                body = ast.parse(path.read_text(encoding="utf-8")).body
                tests = [x for x in body if isinstance(x, ast.FunctionDef) and x.name.startswith("test_")]
                plain = [t.name for t in tests if not any(is_strict_xfail(d) for d in t.decorator_list)]
                if plain or not tests:
                    problems.append(f"{i_id} is 🆕 but {path.name} has tests that are not strict xfail: {plain}")
        else:
            problems.append(f"{doc.name} {i_id} has state {status[:10]!r}; only ✅ or 🆕 are allowed")
    assert not problems, "L2 integration plans vs tests/integration: " + "; ".join(problems)


L3_DOCS = sorted((ROOT / "docs" / "architecture").glob("L3_*.md"))
UNIT_ID = re.compile(r"U-(\w+)-\d+")


def public_names(path: Path) -> set[str]:
    body = ast.parse(path.read_text(encoding="utf-8")).body
    defs = (ast.FunctionDef, ast.ClassDef)
    return {node.name for node in body if isinstance(node, defs) and not node.name.startswith("_")}


def test_l3_modules_match_l2_and_src():
    l2_states = {name: state for doc in L2_DOCS for name, (state, _) in module_table(doc).items()}
    problems = []
    for doc in L3_DOCS:
        for name, (state, names) in module_table(doc).items():
            src = ROOT / "src" / name
            if l2_states.get(name) != state:
                problems.append(f"{name}: L3 state {state!r} differs from L2 {l2_states.get(name)!r}")
            if state == "✅" and src.exists() and public_names(src) != names:
                problems.append(f"{name}: public names {sorted(public_names(src))} differ from L3 {sorted(names)}")
    assert not problems, "L3 module tables: " + "; ".join(problems)


def test_l3_unit_plan_targets_are_tested():
    problems = []
    for doc in L3_DOCS:
        modules = module_table(doc)
        for row in l2_table(doc, "単体テスト計画"):
            match = UNIT_ID.fullmatch(row[0])
            if not match:
                continue
            module = f"{match.group(1)}.py"
            if module not in modules:
                problems.append(f"{row[0]}: {module} is not in the L3 module table")
            elif (ROOT / "src" / module).exists():
                test_file = ROOT / "tests" / "unit" / f"test_{match.group(1)}.py"
                text = test_file.read_text(encoding="utf-8") if test_file.exists() else ""
                missing = [n for n in re.findall(r"`(\w+)`", row[1]) if n not in text]
                if missing:
                    problems.append(f"{row[0]}: {test_file.name} does not test {missing}")
    assert not problems, "L3 unit test plan: " + "; ".join(problems)
