import pytest

from src import config

SECTIONS = {"gatekeeper", "scoring", "recommendation", "output", "tickers", "system", "records"}


def test_loaded_config_has_all_sections():
    assert set(config.CFG) >= SECTIONS
    assert config.CONFIG_FILE.parent == config.ROOT


def test_load_reads_yaml(tmp_path, monkeypatch):
    path = tmp_path / "c.yaml"
    path.write_text('system:\n  market_timezone: "Asia/Tokyo"\n', encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    assert config._load() == {"system": {"market_timezone": "Asia/Tokyo"}}


def test_load_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "missing.yaml")
    with pytest.raises(FileNotFoundError):
        config._load()
