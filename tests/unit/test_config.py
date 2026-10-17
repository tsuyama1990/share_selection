import pytest

from src.config import MissingKeyError, require_key


def test_require_key_returns_the_value():
    assert require_key({"K": "v"}, "K") == "v"


@pytest.mark.parametrize("env", [{}, {"K": ""}])
def test_require_key_raises_for_missing_or_empty(env):
    with pytest.raises(MissingKeyError, match="set K"):
        require_key(env, "K")
