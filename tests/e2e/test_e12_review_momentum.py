"""E12 (not implemented). Placeholder (L1 section 7.2, L2 C4).

`review-eval`, then `review` on a cache with price history: the memo and `sector_comparison` carry the industry's
3-month excess return, its rank among industries and the candidate's position in its industry; candidates unchanged.
"""

import pytest

from tests.fixtures.config import CFG


@pytest.mark.xfail(strict=True, reason="E12: industry momentum in the review memo not implemented")
def test_sector_momentum_is_configured():
    assert "momentum_months" in CFG["sector"]
