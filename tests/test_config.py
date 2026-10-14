import pytest

from src import config

SECTIONS = {"gatekeeper", "indicators", "output", "tickers", "system", "records"}


def test_default_config_is_repo_config_with_all_sections():
    assert config.CONFIG_FILE == config.ROOT / "config.yaml"
    assert set(config.load_config()) >= SECTIONS


def test_load_reads_given_path(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text('output:\n  dir: "exp"\ngatekeeper:\n  psr_cap: 9\n', encoding="utf-8")
    assert config.load_config(path) == {"output": {"dir": "exp"}, "gatekeeper": {"psr_cap": 9}}


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        config.load_config(tmp_path / "missing.yaml")
