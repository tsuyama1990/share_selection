from pathlib import Path

import pytest

LEVELS = ("unit", "integration", "e2e")
TESTS_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items):
    stray = []
    for item in items:
        level = Path(item.path).relative_to(TESTS_DIR).parts[0]
        if level in LEVELS:
            item.add_marker(getattr(pytest.mark, level))
        else:
            stray.append(str(item.path.relative_to(TESTS_DIR.parent)))
    if stray:
        raise pytest.UsageError(f"tests must live in tests/{{{','.join(LEVELS)}}}/: {sorted(set(stray))}")
