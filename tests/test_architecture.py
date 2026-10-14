"""Architecture rules enforced as tests.

(a) ``load_config`` (the config loader) is referenced only by ``src/config.py`` and ``main.py``;
    every other module receives values through ``build_*``/``from_config``/constructor arguments.
(b) ``config.yaml`` and the code agree: every key in the file is read somewhere, and every key the
    code reads exists. Reads are found statically: string-literal subscripts (``x["key"]``) whose
    base is one of ``CONFIG_NAMES`` (the config or an alias of one of its sections, e.g.
    ``sc = cfg["scoring"]``). Matching is by key name, not by full path. Keys under
    ``scoring.shock_lows`` are user-chosen crash names, read dynamically, and are exempt.
"""

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CODE_FILES = sorted((ROOT / "src").glob("*.py")) + [ROOT / "main.py"]
CFG_ALLOWED = {ROOT / "src" / "config.py", ROOT / "main.py"}
CONFIG_NAMES = {"cfg", "CFG", "sc", "gk", "rec", "output_cfg", "imp", "qual"}
DYNAMIC_PARENTS = {"shock_lows"}


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _config_keys(node, parent: str = "") -> set[str]:
    """All dict keys of the YAML tree (list values are data, dynamic mappings are skipped)."""
    keys: set[str] = set()
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
