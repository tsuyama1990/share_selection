# Project conventions

Japanese stock selection with two methods: **Value Turn** (monthly; cheap stocks whose operating-income improvement is confirmed in results, based on Emin Yurumazu's theory; built) and **Tailwind Watch** (research memos on PEST flows you name: companies selling into them with Value Turn results and valuations; decisions recorded and scored; designed in `docs/tailwind_watch_design.md` and `docs/architecture/L2_C9_tailwind.md`, not built). Python 3.12, managed with `uv`.

## Architecture
- `main.py` CLI and wiring only (parse args, load config and `.env`, build parts with `from_config`, `COMMANDS` -> `cmd_<name>`, print summaries; flows live in `src/`): `tickers` (JPX list -> CSV), `fetch` (Yahoo -> DuckDB cache), `analyze` (cache -> `results/` CSV, and a run record), `evaluate` (outcomes of recorded runs), `calendar` (JPX earnings announcement dates -> CSV), `docs [--run RUN_ID]` (EDINET annual report sections of the run's stage 2 candidates -> document store `documents.duckdb`), `review [--run RUN_ID] [--tickers T1,T2]` (LLM research T1-T5 on the run's stage 2 candidates with checked quotes -> `reviews` and a memo per ticker in `results/memos/`; refused until `review-eval` has passed for the prompt version and first model), `backup` (ignored records -> timestamped folders in `backup.dir`, outside the repository), `review-eval` (scores the model on `eval/stage2_cases.yaml` -> `review_evals`; live gate, run by hand after changing models, their order or `prompts/`). `reviews/` (Parquet export) is git-ignored: it quotes web articles.
- `src/`: `stock_data` (typed raw data), `metrics` (pure helpers), `improvement` (stage 2 signs of improvement), `quality` (stage 5 one-off EPS flags), `rules` (gatekeeper), `indicators` (metrics such as Real_PSR, PBR, trend), `fields` (stage 1 result names), `earnings_calendar`, `edinet` (EDINET API v2 index and report sections), `webfetch` (web pages cited by the search: fetch, HTML/PDF text), `docstore` (documents, EDINET index, fetch errors), `collect` (`docs` flow), `screener` (`screen_universe`), `selection` (stage 2 ranking and candidates), `sector` (sector medians and peer comparison), `memo` (Markdown research memo), `throttle` (call-rate limiter shared by EDINET, web and LLM), `cache`, `yahoo`, `records` (`RunInfo`; run records in `records.duckdb` + Parquet export in `records/`, committed; candidates, run metrics), `outcomes` (`evaluate`), `backup` (snapshots of the ignored records), `review_store` (reviews and review evals in `reviews.duckdb`, not committed), `tickers`, `report` (CSV output and eval text), `config`.
- Rules and indicators are dataclasses with injected thresholds, created by `build_rules` / `build_indicators`; `Screener.from_config` wires them.

## Config rule
- Every tunable value, path and file name lives in `config.yaml`.
- Config is loaded with `load_config(path)` (`--config PATH`, default `config.yaml`); only `src/config.py` and `main.py` may reference `load_config`; other modules get values via `build_*` / `from_config` / dataclass fields. `tests/unit/test_architecture.py` enforces this and that config keys and code reads match.
- Add a config key and the code that reads it together (an unused key fails the tests).
- Timestamps: histories are exposed as naive Asia/Tokyo dates (`system.market_timezone`); the cache stores UTC.

## Code style
- NumPy-style docstrings only on public module-level functions/classes whose behavior is not obvious from name and signature. Everywhere else at most a one-line docstring; never restate names or types. Ruff line length 120, no magic numbers in comparisons (PLR2004).

## Test levels
- `tests/unit/`, `tests/integration/`, `tests/e2e/` (marker added from the directory by `tests/conftest.py`; `--strict-markers`). A test module directly under `tests/` fails the run. unit = one class/function, no DB/files/network; integration = component with real collaborators; e2e = CLI flows through `main.py` (L1 §7). `tests/live/` = real-API E2E (L1 §7.1), manual (`uv run pytest -m live --no-cov tests/live`), deselected by default and never in the gate or CI.

## Commands
- `uv sync`; `uv run python main.py [--config PATH] {tickers|fetch|analyze|evaluate}`
- Every rule and scorer runs for every ticker (fail_rule = first failure), so records hold all metrics for replay experiments. Experiment configs must set their own `output.dir`, `records.db_file`, `records.export_dir`.
- Quality gates (all must pass, `scripts/gate.sh` runs them): `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src main.py`, `uv run vulture`, `uv run deptry .`, `uv run pytest` (coverage fail_under = 85).
- Pre-commit hooks: `uv run pre-commit install`.

## Code budget and deletion first
- `[tool.code_budget] max_source_lines` in `pyproject.toml` caps non-blank, non-comment lines of `src/` + `main.py`; `tests/unit/test_code_budget.py` fails when over budget and when the budget is more than 10 lines stale (lower it to the actual count after deleting).
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
- `tests/e2e/test_e1_analyze.py` compares screener output on `tests/fixtures/sample_cache.json.gz` to `tests/fixtures/golden_screening.csv`.
- After an intended change of behavior or `config.yaml` values: `UPDATE_GOLDEN=1 uv run pytest tests/e2e/test_e1_analyze.py`, review the diff, commit it with the change.

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
- `tailwind_watch_design.md` is the agreed plan and lessons for Tailwind Watch (L1 C9, L2 `L2_C9_tailwind.md`); `selection_flow.md` is the target design; `hypothesis_map.md` holds the evidence; `entry_types_design.md` holds reference type definitions for its stage 3; `screening_criteria.md` describes what is implemented now; `selection_tuning.md` records threshold decisions and their evidence.
- Keep docs slim: describe the current design only; a rejected or failed approach becomes a one-line lesson with the reason, history entries are one line each, and details stay in git history (user, 2026-10-18).
- Label every factual claim ([原著]/[一次]/[報道]/[データ: date]/[推論]); recompute numbers with current config and data before committing; check cited examples satisfy the definition; log corrections at the end of the doc.
- Before saying data "cannot be obtained", exhaust the retrieval paths (all yfinance accessors, official public data such as JPX) and state exactly what was tried.

## Development process (`docs/architecture/process.md`)
- Gated modified waterfall: design (L1 `docs/architecture/L1_architecture.md`, L2 `L2_*.md`, L3 `L3_*.md`) -> tests of the same level (E2E / integration / unit) -> implementation -> bonsai. Each step has a blocking gate; do not proceed past a failing one.
- Change top-down: design doc first, then tests, then code. A `src/` module not listed in L1 section 3 fails `tests/unit/test_design_docs.py`.
- Tests live in `tests/unit`, `tests/integration`, `tests/e2e` (marker from directory, `--strict-markers`); shared helpers go in `tests/fixtures/` (cross-level imports fail).
