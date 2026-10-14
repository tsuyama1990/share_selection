# Emin Yurumazu Investment Theory Screener (Hybrid v2.0)

This is a Python-based stock screener implementing the investment philosophy of Emin Yurumazu. It screens Japanese stocks with a gatekeeper and ranks them by improvement of earnings (stage 2 priority).

The system uses a **Hybrid Architecture** with **DuckDB** to separate data accumulation from analysis, ensuring high performance and offline capability.

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
*   `indicators`: metric parameters (Sales CAGR span, moving averages, `shock_lows` crash windows).
*   `improvement`: stage 2 signs of improvement: `clear_threshold` (0.40), `same_quarter_tolerance_days` (20, window around 365 days for the same quarter a year earlier) and `max_quarter_age_days` (200: quarterly EPS older than this vs the price data end is ignored).
*   `quality`: `max_quarter_share_of_annual` (0.5): latest quarterly EPS at or above this share of the latest annual Diluted EPS (> 0) raises `quarter_spike`.
*   `selection`: `candidates_n` (50), the number of top-ranked unflagged `clear` stocks flagged `Stage2_Candidate`.
*   `output`: report `dir`, `filename` and `failures_filename` (`{date}` = YYYY-MM-DD) and the CSV `columns`.
*   `tickers`: `jpx_url` and the `markets` kept by the `tickers` command.
*   `calendar`: `page_url`, `link_pattern` (regex for the workbook links), `user_agent`, `out_csv` of the `calendar` command.
*   `records`: `db_file`, `export_dir` (Parquet backup per run), `shikiho_issue_months` / `shikiho_release_day` (default `--issue`), `horizons_months`, `benchmark_ticker`.
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

This writes the CSV given by `input_csv` (default `japan_tickers.csv`). A custom CSV also works if it has a `code`, `Code`, `ticker` or `Ticker` column. There is no demo list; a missing or invalid file is an error.

### 2b. Earnings Calendar (optional)
Downloads the JPX earnings announcement schedule (one workbook per quarter-end month, linked from the `calendar.page_url` page) and merges it into `calendar.out_csv` (default `earnings_calendar.csv`, git-ignored; columns `code, announce_date, period_en, fiscal_year_end`). A code in several workbooks keeps its earliest announcement date from today on; `announce_date` is empty while undecided. Re-run it before `analyze` (JPX updates the files as companies announce).

```bash
uv run python main.py calendar
```

### 3. Fetch Data (Accumulation)
This command downloads data for tickers whose cache is older than `cache_days` (or missing) and updates the DuckDB cache.
*Run this periodically (e.g., weekly).*

```bash
uv run python main.py fetch
```
Tickers that fail to download are listed with their error in `output.dir`/`output.failures_filename` (default `results/fetch_failures_YYYY-MM-DD.csv`); the path and count are printed. Only a run with failures writes the file.

### 4. Analyze Data (Screening)
This command runs the screening logic using **only the local cache** (it never calls the API, even for stale entries; tickers without a cache are skipped and counted). It is instant.
*Run this as many times as you like while tweaking `config.yaml`.*

```bash
uv run python main.py analyze
```

### 5. Output
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


### 6. Evaluate Outcomes
```bash
uv run python main.py evaluate
```
For each recorded run and each `records.horizons_months` whose horizon has elapsed and has no outcomes yet, computes the return from freshly downloaded adjusted closes (last close on or before each date), the `benchmark_ticker` return and the excess; stores them in `outcomes` and writes `records/<run_id>/outcomes.parquet`.

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

*   **Golden regression**: `tests/test_regression.py` screens 8 cached tickers (`tests/fixtures/sample_cache.json.gz`, exported by `tests/fixtures/export_sample.py`) and compares with `tests/fixtures/golden_screening.csv`. After an intended behavior or config change, regenerate with `UPDATE_GOLDEN=1 uv run pytest tests/test_regression.py` and review the diff.
*   **Architecture tests** (`tests/test_architecture.py`): `load_config` is used only in `src/config.py` and `main.py`; every key of `config.yaml` is read by the code and every key the code reads exists.
*   **Code budget** (`tests/test_code_budget.py`): non-blank, non-comment lines of `src/**/*.py` + `main.py` (docstrings count) must not exceed `[tool.code_budget] max_source_lines` in `pyproject.toml`, and must not fall more than 10 below it (lower the budget when you delete code, so reductions are kept). Raising the budget needs a `Budget-Increase: <reason>` line in a commit message; `scripts/check_budget_increase.sh <base-ref>` checks this in CI (base = merge-base with `origin/main`).
*   **Timezone**: Yahoo history timestamps are Asia/Tokyo; the cache stores them as UTC. `StockCache.get` converts them back so `StockData` histories always have naive local dates (a monthly bar for October is dated `YYYY-10-01`).

## Architecture

*   `main.py`: CLI entry point (`tickers` / `fetch` / `analyze` / `evaluate`).
*   `src/stock_data.py`: `StockData`, the typed raw data of one ticker (normalizes histories to naive market-local dates).
*   `src/metrics.py`: Pure helpers (`to_num`, `sales_cagr`, `avg_turnover`, ...).
*   `src/rules.py`: Gatekeeper rules (one dataclass each) and `build_rules`.
*   `src/indicators.py`: Metric providers (one class each) and `build_indicators`.
*   `src/screener.py`: `Screener` runs rules then indicators and builds the result row.
*   `src/cache.py`: `StockCache` (DuckDB) and `refresh` (download if stale).
*   `src/yahoo.py`: `YahooClient` downloads raw data from Yahoo Finance.
*   `src/records.py`: `RecordStore` (runs, screen_results, outcomes in `records.duckdb`, exported to Parquet) and `evaluate`.
*   `src/tickers.py`: Builds the ticker CSV from the JPX listed company workbook.
*   `src/report.py`: `write_report` writes the dated CSV (location and columns passed in from `output`), `prioritize` adds `Priority_Rank` / `Stage2_Candidate`, and the candidates are printed.
*   `src/config.py`: `load_config(path)` reads a config file (default `config.yaml`; `main.py --config` overrides). Only `config.py` and `main.py` touch it; everything else receives values through `build_*` / `from_config` / dataclass fields.

## Design documents (`docs/`, Japanese)

*   `screening_criteria.md`: current first-screen criteria vs. the original book, decisions and corrections.
*   `hypothesis_map.md`: why-why hypothesis map of what makes prices jump, validated against past cases.
*   `selection_flow.md`: target selection flow (downside safety -> signs of improvement -> catalyst within 6-12 months); open decisions.
*   `selection_tuning.md`: 2026-10-14 tuning of the gate (op margin 5%, PSR 1.2), improvement rule (quarterly-first, 40%), stage-2 ranking by improvement yield, review fixes, with the data behind each decision.
*   `entry_types_design.md`: entry types A-G (to be reorganized under `selection_flow.md` stage 3).

Claims in these documents carry source labels ([原著]/[一次]/[報道]/[データ]/[推論]); numbers are recomputed before each commit.
