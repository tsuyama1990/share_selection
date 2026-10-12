from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / 'config.yaml'

def _load() -> Dict[str, Any]:
    """
    Load config.yaml from the repository root.

    Returns
    -------
    Dict[str, Any]
        Configuration with 'gatekeeper', 'scoring' and 'system' sections.

    Raises
    ------
    FileNotFoundError
        If config.yaml does not exist.
    """
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

CFG = _load()
