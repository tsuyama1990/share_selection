import json
import sys

import duckdb
import yaml

import main
from src.cache import StockCache
from src.config import load_config
from tests.fixtures.sample import load_sample

CFG = load_config()


def test_config_option_redirects_thresholds_and_outputs(tmp_path, monkeypatch):
    alt = {
        **CFG,
        "gatekeeper": {**CFG["gatekeeper"], "psr_cap": 99.0},
        "output": {**CFG["output"], "dir": "alt_out"},
        "system": {**CFG["system"], "db_file": "alt_cache.duckdb"},
        "records": {**CFG["records"], "db_file": "alt_records.duckdb", "export_dir": "alt_records"},
    }
    cfg_path = tmp_path / "alt.yaml"
    cfg_path.write_text(yaml.safe_dump(alt), encoding="utf-8")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    with StockCache(str(tmp_path / "alt_cache.duckdb"), CFG["system"]["market_timezone"]) as cache:
        tickers = load_sample(cache)
    (tmp_path / CFG["system"]["input_csv"]).write_text("\n".join(["code", *tickers]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["main.py", "--config", str(cfg_path), "analyze"])
    main.main()
    with duckdb.connect(str(tmp_path / "alt_records.duckdb")) as con:
        (stored,) = con.execute("SELECT config FROM runs").fetchone()
    assert json.loads(stored)["gatekeeper"]["psr_cap"] == 99.0
    assert (tmp_path / "alt_records").is_dir()
    assert list((tmp_path / "alt_out").glob("*.csv"))
    assert not (tmp_path / CFG["output"]["dir"]).exists()
