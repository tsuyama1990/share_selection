"""E5: `--config` with another file changes thresholds and writes outputs and records elsewhere."""

import json

from tests.e2e.conftest import CFG

ALT = {
    **CFG,
    "gatekeeper": {**CFG["gatekeeper"], "psr_cap": 99.0},
    "output": {**CFG["output"], "dir": "alt_out"},
    "system": {**CFG["system"], "db_file": "alt_cache.duckdb"},
    "records": {**CFG["records"], "db_file": "alt_records.duckdb", "export_dir": "alt_records"},
}


def passed_count(project, cfg) -> int:
    return project.query("SELECT count(*) FROM screen_results WHERE stage1_pass", cfg)[0][0]


def test_config_option_redirects_thresholds_and_outputs(project):
    project.seed_sample(CFG)
    project.seed_sample(ALT)

    project.run("analyze", cfg=ALT)

    (stored,) = project.query("SELECT config FROM runs", ALT)[0]
    assert json.loads(stored)["gatekeeper"]["psr_cap"] == 99.0
    assert (project.root / "alt_records").is_dir()
    assert list((project.root / "alt_out").glob("*.csv"))
    assert not (project.root / CFG["output"]["dir"]).exists()
    assert not (project.root / CFG["records"]["db_file"]).exists()

    project.run("analyze")
    assert passed_count(project, ALT) > passed_count(project, CFG)
