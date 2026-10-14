from unittest import mock

import pandas as pd

import main
from src.cache import StockCache
from src.config import load_config

CFG = load_config()


def test_fetch_writes_failures_csv(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    client = mock.Mock()
    client.download.side_effect = lambda t: {} if t == "1.T" else (_ for _ in ()).throw(RuntimeError("boom"))
    with StockCache(str(tmp_path / "c.duckdb"), CFG["system"]["market_timezone"]) as cache:
        main.run_fetch(CFG, ["1.T", "2.T"], cache, client)
    (path,) = (tmp_path / CFG["output"]["dir"]).glob("fetch_failures_*.csv")
    assert pd.read_csv(path).to_dict("records") == [{"ticker": "2.T", "error": "boom"}]
    assert "1 fetch failures saved" in capsys.readouterr().out
