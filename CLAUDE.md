# Project conventions

Japanese stock screener (Emin Yurumazu's theory). Python 3.12, managed with `uv`.

## Architecture
- `main.py` CLI: `tickers` (JPX list -> CSV), `fetch` (Yahoo -> DuckDB cache), `analyze` (cache -> `results/` CSV, and a run record), `evaluate` (outcomes of recorded runs).
- `src/`: `stock_data` (typed raw data), `metrics` (pure helpers), `improvement` (stage 2 signs of improvement, computed for every cached ticker), `rules` (gatekeeper), `scorers`, `screener`, `cache`, `yahoo`, `records` (run records in `records.duckdb` + Parquet export in `records/`, committed), `tickers`, `report`, `config`.
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

## Claude Code hooks (user-level, `~/.claude/hooks/`)
- Block `git add -A` / `--all` / `.`; block repo edits and `git commit` on `main` (branch first).
- Stop: if the repo has uncommitted non-doc changes, runs `scripts/gate.sh` and blocks finishing until it
  passes; after 3 blocked attempts the session stops with a "NOT DONE" message — report what fails.
- This repo provides `scripts/gate.sh`; keep it identical to the CI steps.

## Golden regression
- `tests/test_regression.py` compares screener output on `tests/fixtures/sample_cache.json.gz` to `tests/fixtures/golden_screening.csv`.
- After an intended change of behavior or `config.yaml` values: `UPDATE_GOLDEN=1 uv run pytest tests/test_regression.py`, review the diff, commit it with the change.

## Workflow and definition of done
1. **Start**: branch from `main` as `<type>/<topic>` (feat, fix, refactor, chore, docs) before touching files.
   Write the done criteria first: requirements with how each is checked, allowed behavior changes
   (none for refactors), and the expected source line delta.
2. **Work**: small commits, one logical change each; every commit passes `scripts/gate.sh`.
3. **Verify** (author): all gates green; golden/full-run diff within the allowed changes; every
   requirement mapped to evidence (test or run output). Delegated agents work in a separate worktree
   branch; the main session re-runs the gates itself before accepting their work.
4. **Merge**: `~/.claude/bin/merge-to-main.sh <branch> <msg-file>` (rebase onto `main` -> `scripts/gate.sh` on the
   rebased branch -> `--no-ff` merge -> delete worktree and branch). Resolve conflicts on the branch, never on `main`.
   Put the requirement -> evidence list in the merge message.
   Conflict prevention: while a delegated agent works, do not edit the files named in its brief on `main`; write
   status notes in shared docs after the merge.
   Behavior-preserving changes (identical golden and full-run output) merge autonomously; changes to
   screening results need the user's approval before merging. Delete the branch after merging.
5. **Stop rules**: after 3 failed attempts at the same gate, stop and report what fails and what was tried.
   Keep cleanup scoped to the diff and touched modules; record minor findings instead of fixing them.
6. Report status as "ready for acceptance" or "merged", never just "done", with the net line delta and
   what was deleted.

## Git rules
- Stage files by explicit path; never `git add -A` / `git add .`.
- Push only when the user asks.
- Never delete or commit `stocks_cache.duckdb` (git-ignored full cache) or `results/`.

## Design docs (`docs/`)
- `selection_flow.md` is the target design; `hypothesis_map.md` holds the evidence; `entry_types_design.md` is to be reorganized under it; `screening_criteria.md` describes what is implemented now.
- Label every factual claim ([原著]/[一次]/[報道]/[データ: date]/[推論]); recompute numbers with current config and data before committing; check cited examples satisfy the definition; log corrections at the end of the doc.
- Before saying data "cannot be obtained", exhaust the retrieval paths (all yfinance accessors, official public data such as JPX) and state exactly what was tried.
