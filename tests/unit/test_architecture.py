"""Architecture rules enforced as tests.

(a) ``load_config`` (the config loader) is referenced only by ``src/config.py`` and ``main.py``;
    every other module receives values through ``build_*``/``from_config``/constructor arguments.
(b) ``config.yaml`` and the code agree: every key in the file is read somewhere, and every key the
    code reads exists. Reads are found statically: string-literal subscripts (``x["key"]``) whose
    base is one of ``CONFIG_NAMES`` (the config or an alias of one of its sections, e.g.
    ``sc = cfg["indicators"]``). Matching is by key name, not by full path. Keys under
    ``indicators.shock_lows`` are user-chosen crash names, read dynamically, and are exempt.
(c) Result-row names and values are strings only in ``src/fields.py``: no other file of ``src/`` or ``main.py``
    repeats one, and dynamic keys (``MA<n>``, ``Downside_to_<name>_Low(%)``) are built by its functions.
(d) Every ``output.columns`` entry is a ``fields.py`` value or a dynamic key built from ``indicators``.
"""

import ast
import re
from pathlib import Path

import yaml

from src import fields

ROOT = Path(__file__).resolve().parents[2]
CODE_FILES = sorted((ROOT / "src").glob("*.py")) + [ROOT / "main.py"]
CFG_ALLOWED = {ROOT / "src" / "config.py", ROOT / "main.py"}
CONFIG_NAMES = {
    "cfg",
    "CFG",
    "sc",
    "gk",
    "rec",
    "output_cfg",
    "imp",
    "qual",
    "llm",
    "search",
    "p",
    "tk",
    "cal",
    "web",
    "ed",
    "check",
    "docs",
}
DYNAMIC_PARENTS = {"shock_lows"}


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _config_keys(node, parent: str = "") -> set[str]:
    """All dict keys of the YAML tree (dicts inside lists included, dynamic mappings skipped)."""
    keys: set[str] = set()
    if isinstance(node, list):
        for item in node:
            keys |= _config_keys(item, parent)
    if isinstance(node, dict) and parent not in DYNAMIC_PARENTS:
        for k, v in node.items():
            keys.add(k)
            keys |= _config_keys(v, k)
    return keys


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _keys_read_by_code() -> set[str]:
    keys: set[str] = set()
    for path in CODE_FILES:
        for node in ast.walk(_parse(path)):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
                and _root_name(node) in CONFIG_NAMES
            ):
                keys.add(node.slice.value)
    return keys


def test_config_is_loaded_only_by_config_and_main():
    offenders = []
    for path in CODE_FILES:
        if path in CFG_ALLOWED:
            continue
        for node in ast.walk(_parse(path)):
            if (isinstance(node, ast.Name) and node.id == "load_config") or (
                isinstance(node, ast.ImportFrom) and any(a.name == "load_config" for a in node.names)
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, f"load_config used outside src/config.py and main.py: {offenders}"


def test_every_config_key_is_consumed_by_code():
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    unused = _config_keys(config) - _keys_read_by_code()
    assert not unused, f"config.yaml keys never read by code: {sorted(unused)}"


def test_every_key_read_by_code_exists_in_config():
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    missing = _keys_read_by_code() - _config_keys(config) - DYNAMIC_PARENTS
    assert not missing, f"keys read by code but absent from config.yaml: {sorted(missing)}"


def test_test_levels_do_not_import_each_other():
    """Shared test helpers live in tests/fixtures; a level never imports another level's test module."""
    tests = Path(__file__).resolve().parent.parent
    bad = [
        f"{p.relative_to(tests)}: {line.strip()}"
        for p in tests.rglob("test_*.py")
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.startswith(("from tests.unit", "from tests.integration", "from tests.e2e", "import tests."))
    ]
    assert not bad, f"cross-level test imports (move helpers to tests/fixtures): {bad}"


FIELDS_FILE = ROOT / "src" / "fields.py"
DYNAMIC_KEY = re.compile(r"MA\d|Downside_to_")


def _field_values() -> set[str]:
    tree = _parse(FIELDS_FILE)
    assert isinstance(tree, ast.Module)
    return {
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }


def _string_literals(path: Path):
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node


def test_result_names_are_defined_only_in_fields():
    values = _field_values()
    offenders = [
        f"{path.relative_to(ROOT)}:{node.lineno} {node.value!r}"
        for path in CODE_FILES
        if path != FIELDS_FILE
        for node in _string_literals(path)
        if node.value in values or DYNAMIC_KEY.match(node.value)
    ]
    assert not offenders, f"result names repeated outside src/fields.py (import them): {offenders}"


def test_output_columns_are_known_fields():
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    ind = config["indicators"]
    known = _field_values() | {fields.ma(ind["ma_short"]), fields.ma(ind["ma_long"])}
    known |= {fields.downside_to_low(name.capitalize()) for name in ind["shock_lows"]}
    unknown = [c for c in config["output"]["columns"] if c not in known]
    assert not unknown, f"output.columns not defined by src/fields.py: {unknown}"
