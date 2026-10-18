# share_selection: Value Turn and Tailwind Watch

A Japanese stock selection pipeline with two screening methods:

| Method | Cadence | Idea | Status |
|---|---|---|---|
| **Value Turn**（割安改善スクリーン） | monthly | Cheap and safe on the downside, with an operating-income improvement that already shows in the results: buy after it is confirmed. Based on Emin Yurumazu's screening theory, with our own thresholds and stage 2 research. | built (this README) |
| **Tailwind Watch**（追い風ウォッチ） | on demand | For a PEST flow (politics, economy, society, technology) you name: a research memo with checked quotes on five axes, the companies selling into it, and their Value Turn results and valuations; your decisions are recorded and scored against a mechanical baseline. Also adds industry momentum facts to Value Turn's memos. | built: `profiles`, `flow-memo`, `flow-decide` (`docs/tailwind_watch_design.md`) |

Value Turn screens all listed stocks with a gatekeeper, ranks them by improvement of earnings, and researches the top candidates with an LLM whose claims must quote the documents. Data accumulation (Yahoo Finance into DuckDB) is separate from analysis, so screening runs offline on the local cache.

## Features

*   **Hybrid System**:
    *   **Fetch Mode**: Downloads raw data (Financials, Balance Sheet, Cash Flow, Quarterly Income Statement, Daily and Monthly History) from Yahoo Finance and stores it in `stocks_cache.duckdb`.
    *   **Analyze Mode**: Runs screening logic against the local database instantly (zero API latency).
*   **Gatekeeper (Fast Screening)**:
    *   Market Cap >= `market_cap_min` (default 3B JPY)
    *   Liquidity: average daily trading value over `turnover_days` (60) sessions >= `turnover_min` (default 30M JPY/day, i.e. order sizes of a few hundred thousand to a few million JPY; see the `Avg_Turnover(M JPY)` output column)
    *   Equity Ratio >= 50% (Configurable). Uses Stockholders' Equity first (Japanese 自己資本比率 definition, excludes non-controlling interests)
    *   Operating Margin >= 5% (Configurable)
    *   PSR Cap <= 1.2
    *   Operating CF > 0 (missing OCF fails)
    *   Missing/NaN metrics FAIL these rules (they no longer slip through). If the latest fiscal year column is unreported (all NaN), the most recent period with values is used.
*   **Reported metrics** (no points; ranking is by `Priority_Rank`):
    *   **Growth**: Sales CAGR over the available 3-4 years.
    *   **Value**: **Real_PSR** (net-cash adjusted PSR), **Net Cash** (cash - total debt, missing debt counts as 0), **Cash / Market Cap**, **PBR**, **Dividend Yield** (forward `dividendYield`, a percent divided by 100; falls back to `trailingAnnualDividendYield`, a fraction).
    *   **Technicals**: Monthly Chart Trend (Price > 12M MA > 24M MA) and the downside to the Lehman (2008-09 to 2009-03) and Corona (2020-02 to 2020-04) monthly lows.

## Installation

This project uses `uv` (Python 3.12+).

```bash
uv sync                      # runtime + dev tools (pytest, ruff, mypy, pre-commit)
uv run pre-commit install    # optional: run the checks on every commit
```

## Usage

### 1. Configuration
Edit `config.yaml` to adjust criteria. Every tunable parameter, path and file name lives there, grouped in sections:

*   `gatekeeper`: pass/fail filters (equity ratio, margin, PSR cap, cash flow, market cap, `turnover_min` / `turnover_days`).
*   `indicators`: metric parameters (Sales CAGR span, moving averages `ma_short` / `ma_long` that also name the `MA<n>` columns, `shock_lows` crash windows).
*   `improvement`: stage 2 signs of improvement: `clear_threshold` (0.40), `same_quarter_tolerance_days` (20, window around 365 days for the same quarter a year earlier) and `max_quarter_age_days` (200: quarterly EPS older than this vs the price data end is ignored).
*   `quality`: `max_quarter_share_of_annual` (0.5): latest quarterly EPS at or above this share of the latest annual Diluted EPS (> 0) raises `quarter_spike`.
*   `selection`: `candidates_n` (50), the number of top-ranked unflagged `clear` stocks flagged `Stage2_Candidate`.
*   `output`: report `dir`, `filename` and `failures_filename` (`{date}` = YYYY-MM-DD) and the CSV `columns`.
*   `tickers`: `jpx_url`, the `markets` kept by the `tickers` command, and `timeout_s` of the download.
*   `calendar`: `page_url`, `link_pattern` (regex for the workbook links), `user_agent`, `timeout_s`, `out_csv` of the `calendar` command.
*   `edinet`: `base_url`, `key_env` (environment variable holding the EDINET API key), `index_days` (first-run index window), `doc_type_code`, `sections` (text blocks stored, including the MD&A where the company explains the profit change; a stored report missing a configured section is downloaded again), `request_interval_s`, `timeout_s` of the `docs` command.
*   `webfetch`: `timeout_s`, `max_bytes` (larger responses are dropped), `user_agent`, `request_interval_s` of the page fetches of `docs`.
*   `docs`: `search` (also collect web sources), `search_prompt` (`{name}`, `{code}`), `max_sources` (per candidate).
*   `docstore`: `db_file` of the document store.
*   `llm`: ordered `providers` (the first with a key is the model `review` is gated on), `search`, `check`, limits (see "LLM" below).
*   `review`: `max_tickers`, `min_verified_ratio`, `prompt_dir` (the prompt version is the hash of its files), `max_doc_chars` (a document is cut to this before the LLM sees it and quotes are checked), `db_file` (`reviews.duckdb`: `reviews` and `review_evals`, apart from `records.duckdb`), `export_dir` (Parquet of `reviews` / `review_evals`, git-ignored), `context_metrics`, `tasks` (answer items of T1-T5, in running order) and `eval` (`cases_file`, `min_hit_rate`, `max_parse_failures`).
*   `backup`: `dir` (default `~/share_selection_backup`; must be outside the repository, which is public) and `keep` (snapshots kept) of the `backup` command.
*   `records`: `db_file`, `export_dir` (Parquet backup per run), `shikiho_issue_months` / `shikiho_release_day` (default `--issue`), `horizons_months`, `benchmark_ticker`, `price_lookback_days` (history fetched before the earliest run by `evaluate`).
*   `system`: `input_csv`, `db_file`, `sleep_time`, `cache_days`, `market_timezone` (timezone of the history timestamps, `Asia/Tokyo`), `daily_history_period`, `monthly_history_period`.

```yaml
gatekeeper:
  equity_ratio_min: 0.45
indicators:
  ma_short: 12
output:
  dir: "results"
system:
  input_csv: "japan_tickers.csv"
```

### 2. Prepare Ticker List
Generate it from the JPX listed company list (Prime / Standard / Growth domestic stocks; JPX updates it monthly):

```bash
uv run python main.py tickers
```

This writes the CSV given by `input_csv` (default `japan_tickers.csv`). A custom CSV also works if it has a `code` column (codes without the `.T` suffix). There is no demo list; a missing or invalid file is an error.

### 3. Earnings Calendar (optional)
Downloads the JPX earnings announcement schedule (one workbook per quarter-end month, linked from the `calendar.page_url` page) and merges it into `calendar.out_csv` (default `earnings_calendar.csv`, git-ignored; columns `code, announce_date, period_en, fiscal_year_end`). A code in several workbooks keeps its earliest announcement date from today on; `announce_date` is empty while undecided. Re-run it before `analyze` (JPX updates the files as companies announce).

```bash
uv run python main.py calendar
```

### 4. Fetch Data (Accumulation)
This command downloads data for tickers whose cache is older than `cache_days` (or missing) and updates the DuckDB cache.
*Run this periodically (e.g., weekly).*

```bash
uv run python main.py fetch
```
Tickers that fail to download are listed with their error in `output.dir`/`output.failures_filename` (default `results/fetch_failures_YYYY-MM-DD.csv`); the path and count are printed. Only a run with failures writes the file.

### 5. Analyze Data (Screening)
This command runs the screening logic using **only the local cache** (it never calls the API, even for stale entries; tickers without a cache are skipped and counted). It is instant.
*Run this as many times as you like while tweaking `config.yaml`.*

```bash
uv run python main.py analyze
```

### 6. Output
Results are saved to `results/emin_screening_result_YYYY-MM-DD.csv` (directory and file name set by `output` in `config.yaml`; `results/` is git-ignored) sorted by `Priority_Rank`; the `Stage2_Candidate` rows are displayed in the console.

Every `analyze` also records the run (all tickers, including those that failed the gatekeeper with the failing rule, and tickers without cache as `no_cache`) in `records.duckdb` and exports it to `records/<run_id>/{runs,screen_results}.parquet`. Commit the `records/` Parquet files as the backup; `records.duckdb` is git-ignored. `--issue YYYY-MM` labels the run with the Shikiho issue used; without it, the latest issue released on or before today is used (issues in `records.shikiho_issue_months`, out on day `records.shikiho_release_day`). Every recorded ticker carries all metrics computable from its cached data (rules and indicators run for gatekeeper failures too, skipping what lacks inputs), so a run can be replayed under other thresholds.

Global option `--config PATH` (before the subcommand, e.g. `uv run python main.py --config experiments/a.yaml analyze`) uses another config file instead of `config.yaml`. Relative paths in any config file stay relative to the repo root. Experiment configs should set their own `output.dir`, `records.db_file` and `records.export_dir` so they do not mix with the main records and results.

**Key Output Columns:**
*   **Next_Earnings_Date**, **Earnings_Period**: next announcement date (`YYYY-MM-DD`, empty if undecided or not listed) and its period (e.g. `Second quarter`) from the calendar CSV; also stored in `screen_results.next_earnings_date` for every ticker. If the calendar file is missing, `analyze` prints one warning and leaves them empty.
*   **EPS_Q_YoY(%)**, **OI_YoY(%)**, **Op_Margin_Change(pt)**: Latest quarter's Diluted EPS vs the same quarter a year earlier (only if that one is positive), latest annual operating income vs the previous year (only if that one is positive), and the change of the annual operating margin in points.
*   **Improvement_Class**: decided by quarterly EPS alone when a fresh year-ago pair is available (YoY; with a loss a year earlier: turnaround to > 0 = `clear`, narrower loss = `signal`, else `none`), otherwise by annual operating income YoY: `clear` (>= `clear_threshold`), `signal` (>= 0), `none` (negative), `unknown` (neither available). Computed for every ticker, including those failing the gatekeeper; recorded in `screen_results.improvement_class` (raw quarterly EPS stays in the metrics JSON).
*   **Improvement_Yield(%)**: size of the improvement relative to the price: annualized quarterly EPS change / price (when quarterly EPS decides), else operating income change / market cap. Unlike growth %, a tiny base does not inflate it.
*   **Quality_Flags**: comma-joined flags on a `clear` class decided by quarterly EPS (empty otherwise): `oi_divergence` (annual `OI_YoY(%)` < 0) and `quarter_spike` (latest quarterly EPS >= `max_quarter_share_of_annual` x latest annual Diluted EPS, annual EPS > 0), i.e. the improvement may come from one-off gains or losses. Also stored as the `rebuttal_flags` list in the run records.
*   **Priority_Rank**, **Stage2_Candidate**: rank 1..n by Improvement_Class (clear > signal > none > unknown), then Improvement_Yield descending, then Real_PSR ascending. `Stage2_Candidate` is True for the first `candidates_n` rows in rank order with class `clear` and empty `Quality_Flags` (flagged rows keep their rank but are skipped, the next clean ones fill the slots). Both are stored in the metrics JSON of passing tickers.
*   **Cash_to_MarketCap_Ratio**: Cash and equivalents / Market Cap.
*   **Net_Cash(Billion)**, **Real_PSR**: Cash - total debt, and (Market Cap - net cash) / sales.
*   **Downside_to_Lehman_Low(%)**, **Downside_to_Corona_Low(%)**: Change from the current price to the lowest monthly low in each crash window.
*   **Chart_Trend**: `Strong Bull` (Perfect Order), `Bull`, or `Bear`.
*   **Sales_CAGR(%)**, **Sales_Growth_Years**: Sales CAGR and the span used (replace `Sales_Growth_4Y(%)`).
*   **Avg_Turnover(M JPY)**: Average daily trading value over `turnover_days` sessions.
*   **PBR**, **PSR**, **Dividend_Yield(%)**: Standard valuation metrics.


### 7. Collect Documents (optional)
Stores the text sections listed in `edinet.sections` of each stage 2 candidate's latest annual securities report (EDINET) in the document store (`docstore.db_file`, default `documents.duckdb`, ignored by version control). The EDINET API key is read from the `edinet.key_env` variable (`EDINET_API_KEY`, environment or `.env`). Run it after `analyze`; `--run RUN_ID` picks another run (default: the latest). The first run indexes the last `edinet.index_days` days of filings (one request of `request_interval_s` per day); later runs add only new days. A report already stored is not fetched again; failures are kept in the `fetch_errors` table and the command goes on.

With `docs.search: true` (default) it also asks Gemini (grounded search, key in the `llm.search.key_env` variable, `GEMINI_API_KEY`) about each candidate's latest results and IR pages (the prompt names the company by its Japanese name from the ticker CSV, best `Priority_Rank` first), then fetches the first `docs.max_sources` cited pages (redirects followed; HTML and PDF text) into the document store as `web:` documents, but only pages whose title or text names the company (its Japanese name or securities code); other pages are kept in `fetch_errors` as `not about the company`. The search answer itself is not stored. A failed search or page is kept in `fetch_errors`.

```bash
uv run python main.py docs [--run RUN_ID]
```

### 8. Review Stage 2 Candidates (LLM)
`review` asks the LLM five tasks per candidate, using only the stored documents (cut to `review.max_doc_chars`): T1 source of the improvement (types P1-P4), T2 one-off gains and losses, T3 use of capital, T4 why the stock is forgotten, then T5 overall (adopt / drop / watch) with the verified T1-T4 answers. Every claim must carry a verbatim quote of one of the documents; the quote is checked after Unicode and whitespace normalization, claims that fail are dropped and an answer item without a verified claim becomes `unknown`. An invalid JSON reply is asked again once with the error; after that the ticker is recorded as `bad_json`. Each ticker gets a row in `reviews` (`ok`, `no_documents`, `llm_failed`, `bad_json`; a failed ticker is retried by the next run), with `verified_ratio` and `needs_attention` (ratio below `review.min_verified_ratio`). The Parquet export goes to `review.export_dir` (`reviews/`, git-ignored: it quotes web articles; never commit it). `--run RUN_ID` picks a run (default: the latest), `--tickers T1,T2` reviews those tickers only (not capped by `max_tickers`). Prompts are files in `review.prompt_dir` (`system.md`, `t1.md`..`t5.md`, `retry.md`). Each reviewed candidate is compared with the median of its 33-sector over all tickers of the run (`sector.metrics`; a median needs `sector.min_peers` values), stored in `reviews.sector_comparison`, and a Markdown memo per `ok` ticker (answers with their verified quotes and sources, unknown items, the peer table, a warning when `needs_attention`) is written to `memo.dir` (`results/memos/`, not committed) as `memo.filename` (`{run_id}_{ticker}.md`). `review-eval` writes no memos.

**Live gate**: `review` refuses to run (exit 1) until `review-eval` has passed for the current prompt version (the hash of the files in `review.prompt_dir`, including the `user.md` layout, so any prompt edit needs a new pass) and the model of the first provider that has a key. `review-eval` collects only the sources in `review.eval.sources` (EDINET: the same documents every run, no search quota) for the tickers in `review.eval.cases_file` (`eval/stage2_cases.yaml`, answers checked against primary sources), reviews them `review.eval.repeats` times and passes only when every repetition passes: hit rate at least `min_hit_rate`, parse failures at most `max_parse_failures`, every ticker's verified ratio at least `review.min_verified_ratio`, and no answer from a fallback provider. The result goes to `review_evals` in `review.db_file`. It uses the real APIs, so it is run by hand, not in CI: rerun it after changing the provider order, the models or any prompt file.

```bash
uv run python main.py review-eval
uv run python main.py review [--run RUN_ID] [--tickers 6599.T,5232.T]
```

### 9. Evaluate Outcomes
```bash
uv run python main.py evaluate
```
For each recorded run and each `records.horizons_months` whose horizon has elapsed and has no outcomes yet, computes the return from freshly downloaded adjusted closes (last close on or before each date), the `benchmark_ticker` return and the excess; stores them in `outcomes` and writes `records/<run_id>/outcomes.parquet`.

### 10. Backup
```bash
uv run python main.py backup
```
Copies what version control does not hold and cannot be fetched again cheaply (`review.db_file`, `review.export_dir`, `memo.dir`, `docstore.db_file`) to `backup.dir/<YYYYMMDDTHHMMSS>/`, skips missing sources (listed in the output) and deletes the oldest snapshot folders beyond `backup.keep`; other folders in `backup.dir` are never touched. It refuses (exit 1) when `backup.dir` is inside the repository. `records.duckdb` is not copied: its Parquet export is committed.

### 11. LLM Check (stage 2)
```bash
uv run python main.py llm-check
```
Smoke test: sends one prompt through the provider fallback chain and one Gemini grounded-search query, and prints which provider/model answered, the answer length and the number of sources (never keys).

The `llm:` section of `config.yaml` holds the ordered `providers` (name, base_url, model, `key_env`), `timeout_s`, `temperature`, `max_calls_per_minute`, `search` and `check` (the two prompts of `llm-check`). A provider whose `key_env` variable is empty is skipped; on HTTP errors (e.g. 429, 5xx), timeouts or connection errors the next provider is tried. API keys are never put in the config: they come from environment variables, optionally loaded at startup from a git-ignored `.env` in the repo root (`KEY=value` lines; variables already set in the shell win over `.env`).

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
Runs the CLI end to end against the real JPX, Yahoo, EDINET, Gemini and LLM APIs (scenarios LV1-LV13 of L1 section 7.1). All outputs, records and the document store go to a temporary directory; the repo's `.env` is only read and `stocks_cache.duckdb` only read by `analyze`. It spends API quota (Gemini search is limited to about 20 requests a day) and takes tens of minutes, so it is deselected by default and never runs in CI or `scripts/gate.sh`.

## Architecture

*   `main.py`: CLI and wiring only (argument parsing, config and `.env` loading, parts built by their `from_config`, one `cmd_<name>` per command in `COMMANDS`, summaries printed); the flows live in `src/`.
*   `src/collect.py`: the `docs` flow (`collect_documents`): EDINET index and annual reports, then a Gemini search per candidate without web documents (given best `Priority_Rank` first by `RecordStore.candidates`, stops at the search quota); `companies` turns candidates into `Company` rows with the Japanese names.
*   `src/review.py`: the `review` flow (`review_candidates`, `ReviewDeps.from_config` opens its parts): documents -> T1-T5 -> `reviews` row, a failing ticker is recorded and the flow goes on. `src/research.py` runs one task (prompt files, JSON mode, one re-ask), `src/verify.py` checks quotes, `src/review_eval.py` scores and judges the eval cases.
*   `src/stock_data.py`: `StockData`, the typed raw data of one ticker (normalizes histories to naive market-local dates).
*   `src/fields.py`: The stage-1 result vocabulary (row keys, improvement classes and sources, `ma` / `downside_to_low`); no other module repeats these strings (architecture test).
*   `src/metrics.py`: Pure helpers (`to_num`, `latest_values`, `sales_cagr`, `avg_turnover`, ...).
*   `src/rules.py`: Gatekeeper rules (one dataclass each) and `build_rules`.
*   `src/indicators.py`: Metric providers (one class each) and `build_indicators`.
*   `src/screener.py`: `Screener` runs rules then indicators and builds the result row; `screen_universe` screens all tickers (`NO_CACHE` when not cached) and adds the earnings calendar fields.
*   `src/cache.py`: `StockCache` (DuckDB), `refresh` (download if stale) and `refresh_all` (returns the failed tickers).
*   `src/yahoo.py`: `YahooClient` downloads raw data from Yahoo Finance.
*   `src/records.py`: `RecordStore` (runs, screen_results, outcomes in `records.duckdb`, exported to Parquet; `candidates` in `Priority_Rank` order, `resolve_run`); `RunInfo` holds the run metadata (`latest_issue`, `git_sha` gather it) and `record_run(RunInfo, results)` builds the columns from `ScreenResult` rows.
*   `src/backup.py`: `backup` (timestamped snapshots of the ignored records outside the repository, pruned to `backup.keep`) and `backup_from_config`.
*   `src/outcomes.py`: `evaluate` computes the outcomes of the recorded runs whose horizons have elapsed.
*   `src/review_store.py`: `ReviewStore` (`reviews` and `review_evals` in `reviews.duckdb`, Parquet to `review.export_dir`) and `ReviewRow`.
*   `src/edinet.py`: `EdinetClient` (EDINET API v2), the filing index update and `fetch_annual_report` (text sections of the latest annual securities report).
*   `src/webfetch.py`: `fetch_document` (a cited URL -> redirects followed, size limit, HTML/PDF text -> document store), `extract_text`, `web_doc_id`.
*   `src/docstore.py`: `DocStore` (`documents.duckdb`: documents, EDINET index, fetch errors); a stored text is never rewritten.
*   `src/tickers.py`: Builds the ticker CSV from the JPX listed company workbook (`update_ticker_csv`) and reads it (`read_tickers`).
*   `src/selection.py`: `prioritize` adds `Priority_Rank` / `Stage2_Candidate` (class, then improvement yield, then Real_PSR).
*   `src/throttle.py`: `RateLimiter` (sliding window) shared by the EDINET, web and LLM clients.
*   `src/report.py`: `format_eval` formats a `review-eval`; `write_failures` writes the fetch failures CSV; `write_report` writes the dated CSV (location and columns passed in from `output`) and prints the candidates.
*   `src/config.py`: `load_config(path)` reads a config file (default `config.yaml`; `main.py --config` overrides); `require_key(env, name)` is the one place API keys are checked (`MissingKeyError`). Only `config.py` and `main.py` touch it; everything else receives values through `build_*` / `from_config` / dataclass fields.

## Design documents (`docs/`, Japanese)

*   `screening_criteria.md`: current first-screen criteria vs. the original book, decisions and corrections.
*   `hypothesis_map.md`: why-why hypothesis map of what makes prices jump, validated against past cases.
*   `selection_flow.md`: target selection flow (downside safety -> signs of improvement -> catalyst within 6-12 months); open decisions.
*   `tailwind_watch_design.md`: Tailwind Watch: what the 2026-10-18 tests taught (mechanical early signals did not work) and the resulting plan (Value Turn memo additions, research memos on flows you name, decision scoring). Detailed design: `architecture/L2_C9_tailwind.md`.
*   `selection_tuning.md`: 2026-10-14 tuning of the gate (op margin 5%, PSR 1.2), improvement rule (quarterly-first, 40%), stage-2 ranking by improvement yield, review fixes, with the data behind each decision.
*   `record_design.md`: stage 7 records (runs, screen_results, outcomes, reviews) derived from the verification questions.
*   `architecture/process.md`: the gated modified-waterfall process (design -> tests -> implementation -> bonsai, each with a blocking gate).
*   `architecture/L1_architecture.md`: requirements, components C1-C8, data contracts, E2E plan (checked by `tests/unit/test_design_docs.py`).
*   `architecture/L2_C2_data_acquisition.md`, `architecture/L2_C4_stage2_research.md`: detailed designs and integration test plans.
*   `entry_types_design.md`: reference definitions of entry types A-G (input for the stage 3 design in `selection_flow.md`).

Claims in these documents carry source labels ([原著]/[一次]/[報道]/[データ]/[推論]); numbers are recomputed before each commit.
