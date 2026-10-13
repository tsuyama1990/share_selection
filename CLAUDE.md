# Project conventions

Japanese stock screener (Emin Yurumazu's theory). Python 3.12, managed with `uv`.

## Architecture
- `main.py` CLI: `tickers` (JPX list -> CSV), `fetch` (Yahoo -> DuckDB cache), `analyze` (cache -> `results/` CSV).
- `src/`: `stock_data` (typed raw data), `metrics` (pure helpers), `rules` (gatekeeper), `scorers`, `screener`, `cache`, `yahoo`, `tickers`, `report`, `config`.
- Rules and scorers are dataclasses with injected thresholds, created by `build_rules` / `build_scorers`; `Screener.from_config` wires them.

## Config rule
- Every tunable value, path and file name lives in `config.yaml`.
- Only `src/config.py` and `main.py` may reference `CFG`; other modules get values via `build_*` / `from_config` / dataclass fields. `tests/test_architecture.py` enforces this and that config keys and code reads match.
- Add a config key and the code that reads it together (an unused key fails the tests).
- Timestamps: histories are exposed as naive Asia/Tokyo dates (`system.market_timezone`); the cache stores UTC.

## Code style
- NumPy-style docstrings only on public module-level functions/classes whose behavior is not obvious from name and signature. Everywhere else at most a one-line docstring; never restate names or types. Ruff line length 120, no magic numbers in comparisons (PLR2004).

## Commands
- `uv sync`; `uv run python main.py {tickers|fetch|analyze}`
- Quality gates (all must pass, `scripts/gate.sh` runs them): `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src main.py`, `uv run vulture`, `uv run deptry .`, `uv run pytest` (coverage fail_under = 85).
- Pre-commit hooks: `uv run pre-commit install`.

## Code budget and deletion first
- `[tool.code_budget] max_source_lines` in `pyproject.toml` caps non-blank, non-comment lines of `src/` + `main.py`; `tests/test_code_budget.py` fails when over budget and when the budget is more than 10 lines stale (lower it to the actual count after deleting).
- Raising the budget requires a `Budget-Increase: <reason>` line in a commit message of the branch (`scripts/check_budget_increase.sh`, run in CI).
- Prefer deleting to adding: remove what vulture reports instead of whitelisting, inline abstractions with one caller/implementation, drop unused parameters, fields and keys, and do not add docstrings or comments that restate names or types.
- Complexity limits (ruff C901 <= 10, PLR0912/0913/0915) are fixed by simplifying, not by `noqa`.
- Dead code (`vulture`) and dependency drift (`deptry`) are gates alongside ruff, mypy and pytest.

## Claude Code hooks (`.claude/settings.json`)
- PreToolUse on Bash (`scripts/hooks/block_git_add_all.sh`): blocks `git add -A`, `--all` and `git add .`; stage explicit paths.
- Stop (`scripts/hooks/stop_gate.sh`): if `src`, `main.py`, `tests`, `config.yaml` or `pyproject.toml` have uncommitted changes, runs `scripts/gate.sh` and blocks finishing until it passes.

## Golden regression
- `tests/test_regression.py` compares screener output on `tests/fixtures/sample_cache.json.gz` to `tests/fixtures/golden_screening.csv`.
- After an intended change of behavior or `config.yaml` values: `UPDATE_GOLDEN=1 uv run pytest tests/test_regression.py`, review the diff, commit it with the change.

## Git rules
- Stage files by explicit path; never `git add -A` / `git add .`.
- One logical change per commit with a clear message. Do not push unless asked.
- Never delete or commit `stocks_cache.duckdb` (git-ignored full cache) or `results/`.
