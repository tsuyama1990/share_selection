import sys
from pathlib import Path

import duckdb
import pytest
import yaml

import main
from src.cache import StockCache
from tests.fixtures.config import CFG
from tests.fixtures.sample import load_sample


class Project:
    """A throw-away repo root: `main.ROOT` points here and commands run through `main.main()`."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch):
        self.root = root
        self.monkeypatch = monkeypatch

    def seed_sample(self, cfg: dict = CFG) -> list[str]:
        """Fill the cache with the fixture sample and write the ticker CSV; return the tickers."""
        with StockCache(str(self.root / cfg["system"]["db_file"]), cfg["system"]["market_timezone"]) as cache:
            tickers = load_sample(cache)
        self.write_tickers(tickers, cfg)
        return tickers

    def write_tickers(self, tickers: list[str], cfg: dict = CFG) -> None:
        (self.root / cfg["system"]["input_csv"]).write_text(
            "\n".join(["code", *(t.removesuffix(".T") for t in tickers)]) + "\n", encoding="utf-8"
        )

    def run(self, *args: str, cfg: dict = CFG) -> None:
        config_path = self.root / "test_config.yaml"
        config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        self.monkeypatch.setattr(sys, "argv", ["main.py", "--config", str(config_path), *args])
        main.main()

    def query(self, sql: str, cfg: dict = CFG) -> list[tuple]:
        with duckdb.connect(str(self.root / cfg["records"]["db_file"])) as con:
            return con.execute(sql).fetchall()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    return Project(tmp_path, monkeypatch)
