"""I-C9-3: the numbers of a mapped company are the run record, the sector comparison and the momentum of the cache,
put side by side as they are (L2 C9 section 7)."""

import pytest

from src.fields import IMPROVEMENT_CLASS
from src.flow import FAIL_RULE, PER, STAGE1_PASS, company_numbers
from src.sector import Peers, compare, sector_medians
from tests.fixtures.config import CFG

SECTOR = "水産・農林業"
METRICS = list(CFG["sector"]["metrics"])
SECTORS = {"1.T": SECTOR, "2.T": SECTOR}
RUN_METRICS = {
    "1.T": {METRICS[0]: 0.5, METRICS[1]: 0.8, METRICS[2]: 10.0},
    "2.T": {METRICS[0]: 1.5, METRICS[1]: 1.2, METRICS[2]: 30.0},
}
ROW = {STAGE1_PASS: True, FAIL_RULE: "psr_cap", IMPROVEMENT_CLASS: "clear", PER: 12.5, **RUN_METRICS["1.T"]}
PER_MAX = 100


def make_peers() -> Peers:
    """The sector medians of the two tickers, as the flow builds them from the run record."""
    medians = sector_medians(RUN_METRICS, SECTORS, METRICS, 1)
    return Peers(medians, SECTORS, METRICS, tuple(RUN_METRICS))


def test_numbers_come_from_the_record_the_comparison_and_the_momentum() -> None:
    numbers = company_numbers("1.T", ROW, make_peers(), {"position": 0.25}, PER_MAX)

    assert numbers[STAGE1_PASS] is True
    assert numbers["fail_rule"] == "psr_cap"
    assert numbers["improvement_class"] == "clear"
    assert numbers["position"] == 0.25
    assert numbers["per"] == 12.5
    assert numbers["overvalued"] is False
    assert numbers["sector_comparison"] == compare("1.T", ROW, make_peers())
    assert numbers["sector_comparison"]["sector"] == SECTOR
    assert numbers["sector_comparison"]["metrics"][METRICS[0]]["value"] == 0.5
    assert numbers["sector_comparison"]["metrics"][METRICS[0]]["median"] == pytest.approx(1.0)


def test_missing_items_stay_null_and_only_a_high_per_is_flagged() -> None:
    numbers = company_numbers("1.T", {}, make_peers(), {}, PER_MAX)

    assert numbers[STAGE1_PASS] is None
    assert numbers["fail_rule"] is None
    assert numbers["improvement_class"] is None
    assert numbers["position"] is None
    assert numbers["per"] is None
    assert numbers["overvalued"] is False
    assert company_numbers("1.T", {PER: PER_MAX}, make_peers(), {}, PER_MAX)["overvalued"] is True
    assert company_numbers("1.T", {PER: float("nan")}, make_peers(), {}, PER_MAX)["per"] is None
    assert company_numbers("1.T", {PER: True}, make_peers(), {}, PER_MAX)["per"] is None
