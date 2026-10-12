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
- NumPy-style docstrings on public functions and classes. Ruff line length 120, no magic numbers in comparisons (PLR2004).

## Commands
- `uv sync`; `uv run python main.py {tickers|fetch|analyze}`
- Quality gates (all must pass): `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src main.py`, `uv run pytest` (coverage fail_under = 85).
- Pre-commit hooks: `uv run pre-commit install`.

## Golden regression
- `tests/test_regression.py` compares screener output on `tests/fixtures/sample_cache.json.gz` to `tests/fixtures/golden_screening.csv`.
- After an intended change of behavior or `config.yaml` values: `UPDATE_GOLDEN=1 uv run pytest tests/test_regression.py`, review the diff, commit it with the change.

## Git rules
- Stage files by explicit path; never `git add -A` / `git add .`.
- One logical change per commit with a clear message. Do not push unless asked.
- Never delete or commit `stocks_cache.duckdb` (git-ignored full cache) or `results/`.
