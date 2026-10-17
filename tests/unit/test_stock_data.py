import pandas as pd

from tests.fixtures.stock import make_stock


def test_a_history_index_that_is_not_dates_is_kept_as_it_is():
    history = pd.DataFrame({"Close": [1.0]}, index=["not a date"])
    assert make_stock("T", {"history": history}).history.index.tolist() == ["not a date"]
