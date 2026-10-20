# share_selection: Value Turn and Tailwind Watch

A Japanese stock selection pipeline with two methods. They were built against each other: each one's weakness is what the other covers.

| | **Value Turn**（割安改善スクリーン） | **Tailwind Watch**（追い風ウォッチ） |
|---|---|---|
| Cadence | monthly | on demand |
| Idea | Cheap and safe on the downside, with an operating-income improvement that already shows in the results: buy after it is confirmed. Based on Emin Yurumazu's screening theory, with our own thresholds and an LLM stage 2 whose claims must quote the documents. | For a PEST flow you name (politics, economy, society, technology): a research memo on five axes with checked quotes, the companies selling into it with their Value Turn results and valuations; your decisions are recorded and scored against a mechanical baseline. |
| Strength | Evidence-based: acts on profits that were reported. Slow but hard to fool. | Reaches a theme before profits show, and finds quiet beneficiaries (not the first names that come to mind). |
| Weakness | Late by design. | Judgment-based and risky: mechanical early signals did not beat the market in our tests, so a person decides and the record keeps score. |
| Commands | `tickers` `fetch` `calendar` `analyze` `docs` `review-eval` `review` `evaluate` `backup` | `profiles` `flow-memo` `flow-decide` (and `evaluate` scores the decisions) |
| Guide | [`docs/value_turn.md`](docs/value_turn.md) | [`docs/tailwind_watch_design.md`](docs/tailwind_watch_design.md) |

Both share the document store (EDINET sections), the quote-checking LLM stage and the records. Data accumulation (Yahoo Finance into DuckDB) is separate from analysis, so screening runs offline on the local cache. New session? Read [`docs/handoff.md`](docs/handoff.md) first.


## Installation

This project uses `uv` (Python 3.12+).

```bash
uv sync                      # runtime + dev tools (pytest, ruff, mypy, pre-commit)
uv run pre-commit install    # optional: run the checks on every commit
```

## Commands

```bash
uv run python main.py [--config PATH] <command>
```

| Command | What it does |
|---|---|
| `tickers` | JPX listed companies -> `japan_tickers.csv` |
| `fetch` | Yahoo Finance -> local cache (run periodically) |
| `calendar` | JPX earnings announcement dates -> CSV |
| `analyze` | Screen the cache -> `results/` CSV and a run record |
| `docs` | EDINET sections and cited web pages of the run's stage 2 candidates -> document store |
| `review-eval` / `review` | Gate the LLM model on checked answers / research the candidates with checked quotes |
| `evaluate` | Score recorded runs (and flow decisions) after 6 and 12 months |
| `backup` | Copy the git-ignored records outside the repository |
| `llm-check` | Smoke test of the LLM providers |
| `profiles` | Business sections of every listed company -> document store (Tailwind Watch) |
| `flow-memo` | Research memo on a flow you name (Tailwind Watch) |
| `flow-decide` | Record a decision on a company of a flow (Tailwind Watch) |

Every tunable value, path and file name lives in `config.yaml`; API keys come from environment variables or a git-ignored `.env`.


## Testing and quality gates

```bash
uv run pytest                          # tests + coverage (fail_under = 85)
uv run ruff check                      # lint (E,F,W,I,B,UP,SIM,PLR2004, complexity C901<=10, PLR0912/0913/0915)
uv run ruff format --check             # formatting (use `ruff format` to apply)
uv run mypy src main.py                # types
uv run vulture                         # dead code (src, main.py; min confidence 60)
uv run deptry .                        # declared vs imported dependencies
scripts/gate.sh                        # all of the above
```

The same checks run in CI (`.github/workflows/ci.yml`) and, except pytest, in pre-commit (`.pre-commit-config.yaml`).

*   **Golden regression**: `tests/e2e/test_e1_analyze.py` screens 8 cached tickers (`tests/fixtures/sample_cache.json.gz`, exported by `tests/fixtures/export_sample.py`) and compares with `tests/fixtures/golden_screening.csv`. After an intended behavior or config change, regenerate with `UPDATE_GOLDEN=1 uv run pytest tests/e2e/test_e1_analyze.py` and review the diff.
*   **Architecture tests** (`tests/unit/test_architecture.py`): `load_config` is used only in `src/config.py` and `main.py`; every key of `config.yaml` is read by the code and every key the code reads exists.
*   **Code budget** (`tests/unit/test_code_budget.py`): non-blank, non-comment lines of `src/**/*.py` + `main.py` (docstrings count) must not exceed `[tool.code_budget] max_source_lines` in `pyproject.toml`, and must not fall more than 10 below it (lower the budget when you delete code, so reductions are kept). Raising the budget needs a `Budget-Increase: <reason>` line in a commit message; `scripts/check_budget_increase.sh <base-ref>` checks this in CI (base = merge-base with `origin/main`).
*   **Timezone**: Yahoo history timestamps are Asia/Tokyo; the cache stores them as UTC. `StockCache.get` converts them back so `StockData` histories always have naive local dates (a monthly bar for October is dated `YYYY-10-01`).

## Live E2E

```bash
uv run pytest -m live --no-cov tests/live
```
Runs the CLI end to end against the real JPX, Yahoo, EDINET, Gemini and LLM APIs (scenarios LV1-LV16 of L1 section 7.1, including `profiles`, `flow-memo` and `flow-decide`). All outputs, records and the document store go to a temporary directory; the repo's `.env` is only read and `stocks_cache.duckdb` only read by `analyze`. It spends API quota (Gemini search is limited to about 20 requests a day) and takes tens of minutes, so it is deselected by default and never runs in CI or `scripts/gate.sh`.

## Architecture

*   `main.py`: CLI and wiring only (argument parsing, config and `.env` loading, parts built by their `from_config`, one `cmd_<name>` per command in `COMMANDS`, summaries printed); the flows live in `src/`.
*   `src/flows.py`: the flows that compose several components, one function per command (`fetch_run`, `analyze_run`, `collect_run`, `profiles_run`, `review_run`, `review_eval_run`, `flow_memo_run`).
*   `src/collect.py`: the `docs` flow (`collect_documents`): EDINET index and annual reports, then a Gemini search per candidate without web documents (given best `Priority_Rank` first by `RecordStore.candidates`, stops at the search quota); `companies` turns candidates into `Company` rows with the Japanese names.
*   `src/review.py`: the `review` flow (`review_candidates`, `ReviewDeps.from_config` opens its parts): documents -> T1-T5 -> `reviews` row, a failing ticker is recorded and the flow goes on. `src/research.py` runs one task (prompt files, JSON mode, one re-ask), `src/verify.py` checks quotes, `src/review_eval.py` scores and judges the eval cases.
*   `src/stock_data.py`: `StockData`, the typed raw data of one ticker (normalizes histories to naive market-local dates).
*   `src/fields.py`: The stage-1 result vocabulary (row keys, improvement classes and sources, `ma` / `downside_to_low`); no other module repeats these strings (architecture test).
*   `src/metrics.py`: Pure helpers (`to_num`, `latest_values`, `sales_cagr`, `avg_turnover`, `close_on_or_before`, `period_return`, ...).
*   `src/rules.py`: Gatekeeper rules (one dataclass each) and `build_rules`.
*   `src/indicators.py`: Metric providers (one class each) and `build_indicators`.
*   `src/screener.py`: `Screener` runs rules then indicators and builds the result row; `screen_universe` screens all tickers (`NO_CACHE` when not cached) and adds the earnings calendar fields.
*   `src/cache.py`: `StockCache` (DuckDB), `refresh` (download if stale), `refresh_all` (returns the failed tickers), and readers of the cache for the flows (`closes_of`, `price_earnings`).
*   `src/yahoo.py`: `YahooClient` downloads raw data from Yahoo Finance.
*   `src/records.py`: `RecordStore` (runs, screen_results, outcomes in `records.duckdb`, exported to Parquet; `candidates` in `Priority_Rank` order, `resolve_run`); `RunInfo` holds the run metadata (`latest_issue`, `git_sha` gather it) and `record_run(RunInfo, results)` builds the columns from `ScreenResult` rows.
*   `src/backup.py`: `backup` (timestamped snapshots of the ignored records outside the repository, pruned to `backup.keep`) and `backup_from_config`.
*   `src/outcomes.py`: `evaluate` computes the outcomes of the recorded runs whose horizons have elapsed; `evaluate_decisions` scores the flow decisions against the same-sector control group.
*   `src/sector.py`: peer medians and comparison (`Peers`, `compare`), industry momentum (`Universe`, `momentum`, `momentum_note`) and `laggard_peers` (the control group); `src/memo.py`: the Markdown memos of `review` (`render_memo`) and of `flow-memo` (`render_flow_memo`).
*   `src/flow.py`: the `flow-memo` / `flow-decide` flow (`flow_memo`, `FlowDeps.from_config`, `company_numbers`, `Decision`); `src/company_map.py`: the company map (search terms, ranking over the business sections, LLM confirmation with quotes); `src/flow_store.py`: `FlowStore` (`flow.duckdb`: flows, axes, map, decisions, outcomes).
*   `src/review_store.py`: `ReviewStore` (`reviews` and `review_evals` in `reviews.duckdb`, Parquet to `review.export_dir`) and `ReviewRow`.
*   `src/edinet.py`: `EdinetClient` (EDINET API v2), the filing index update and `fetch_annual_report` (text sections of the latest annual securities report).
*   `src/webfetch.py`: `fetch_document` (a cited URL -> redirects followed, size limit, HTML/PDF text -> document store, only if the page names the company), `fetch_page` (the same without the company check, for a flow's sources), `download`, `extract_text`, `web_doc_id`.
*   `src/docstore.py`: `DocStore` (`documents.duckdb`: documents, EDINET index, fetch errors); a stored text is never rewritten.
*   `src/tickers.py`: Builds the ticker CSV from the JPX listed company workbook (`update_ticker_csv`) and reads it (`read_tickers`).
*   `src/selection.py`: `prioritize` adds `Priority_Rank` / `Stage2_Candidate` (class, then improvement yield, then Real_PSR).
*   `src/throttle.py`: `RateLimiter` (sliding window) shared by the EDINET, web and LLM clients.
*   `src/report.py`: `format_eval` formats a `review-eval`; `write_failures` writes the fetch failures CSV; `write_report` writes the dated CSV (location and columns passed in from `output`) and prints the candidates.
*   `src/config.py`: `load_config(path)` reads a config file (default `config.yaml`; `main.py --config` overrides); `require_key(env, name)` is the one place API keys are checked (`MissingKeyError`). Only `config.py` and `main.py` touch it; everything else receives values through `build_*` / `from_config` / dataclass fields.

## Design documents (`docs/`, Japanese)

*   `handoff.md`: read first in a new session: state, runbook, open decisions, next steps, pitfalls.
*   Value Turn: `value_turn.md` (usage, settings, outputs), `selection_flow.md` (the flow and its state), `selection_tuning.md` (threshold decisions and evidence), `screening_criteria.md` (criteria vs. the book), `hypothesis_map.md` (why-why map of what makes prices jump), `entry_types_design.md` (reference entry types), `record_design.md` (records and outcomes).
*   Tailwind Watch: `tailwind_watch_design.md` (plan, lessons, usage).
*   Process and design: `architecture/process.md` (gated modified waterfall), `architecture/L1_architecture.md` (requirements, components C1-C9, E2E plan), `architecture/L2_*.md` (detailed designs, integration test plans), `architecture/L3_*.md` (class designs, unit test plans; public names are checked against `src/`).

Claims in these documents carry source labels ([原著]/[一次]/[報道]/[データ]/[推論]); numbers are recomputed before each commit.
