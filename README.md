# Emin Yurumazu Investment Theory Screener (Hybrid v2.0)

This is a Python-based stock screener implementing the investment philosophy of Emin Yurumazu. It is designed to find **Quality Growth** and **Quality Value** stocks in the Japanese market.

The system uses a **Hybrid Architecture** with **DuckDB** to separate data accumulation from analysis, ensuring high performance and offline capability.

## Features

*   **Hybrid System**:
    *   **Fetch Mode**: Downloads raw data (Financials, Balance Sheet, Monthly History) from Yahoo Finance and stores it in `stocks_cache.duckdb`.
    *   **Analyze Mode**: Runs screening logic against the local database instantly (zero API latency).
*   **Gatekeeper (Fast Screening)**:
    *   Market Cap >= `market_cap_min` (default 100M JPY)
    *   Liquidity: 60-day average daily trading value >= `turnover_min` (default 10M JPY, intentionally low; use the `Avg_Turnover_60D(M JPY)` output column to narrow later)
    *   Equity Ratio >= 45% (Configurable). Uses Stockholders' Equity first (Japanese 自己資本比率 definition, excludes non-controlling interests)
    *   Operating Margin >= 10% (Configurable)
    *   PSR Cap <= 2.5
    *   Operating CF > 0 (missing OCF fails)
    *   Missing/NaN metrics FAIL these rules (they no longer slip through). If the latest fiscal year column is unreported (all NaN), the most recent period with values is used.
*   **Scoring System**:
    *   **Growth**: Sales CAGR over the available 3-4 years; threshold `sales_cagr_threshold` 0.189 (= 2x over 4 years).
    *   **Value**: PSR, **PBR**, **Dividend Yield** (>=3%, from `trailingAnnualDividendYield` as a fraction; yfinance `dividendYield` is in percent and only a fallback, divided by 100), **PER Growth** (Forward < Trailing), **Cash Ratio** (Net-Net).
    *   **Technicals**: **Monthly Chart Trend** (Price > 12M MA > 24M MA), scored under Score_Safety.

## Installation

This project uses `uv` for dependency management.

```bash
uv add yfinance pandas tqdm pyyaml duckdb
```

Or using pip:
```bash
pip install yfinance pandas tqdm pyyaml duckdb
```

## Usage

### 1. Configuration
Edit `config.yaml` to adjust criteria.

```yaml
gatekeeper:
  equity_ratio_min: 0.45
scoring:
  sales_growth_points: 3
  technical_points: 2
system:
  input_csv: "japan_tickers.csv"
```

### 2. Prepare Ticker List
Ensure the CSV given by `input_csv` (default `japan_tickers.csv`) exists and has a `code`, `Code`, `ticker` or `Ticker` column. There is no demo list; a missing or invalid file is an error.

### 3. Fetch Data (Accumulation)
This command downloads data for tickers whose cache is older than `cache_days` (or missing) and updates the DuckDB cache.
*Run this periodically (e.g., weekly).*

```bash
python3 main.py fetch
```

### 4. Analyze Data (Screening)
This command runs the screening logic using **only the local cache** (it never calls the API, even for stale entries; tickers without a cache are skipped and counted). It is instant.
*Run this as many times as you like while tweaking `config.yaml`.*

```bash
python3 main.py analyze
```

### 5. Output
Results are saved to `emin_screening_result_YYYY-MM-DD.csv` and displayed in the console.

**Key Output Columns:**
*   **Recommendation_Type**: `Quality Growth`, `Quality Value`, `NET-NET`, or `Watch`.
*   **Cash_to_MarketCap_Ratio**: > 1.0 means the company has more cash than its market value (Net-Net).
*   **Chart_Trend**: `Strong Bull` (Perfect Order), `Bull`, or `Bear`.
*   **Sales_CAGR(%)**, **Sales_Growth_Years**: Sales CAGR and the span used (replace `Sales_Growth_4Y(%)`).
*   **Avg_Turnover_60D(M JPY)**: 60-day average daily trading value.
*   **PBR**, **PSR**, **Dividend_Yield**: Standard valuation metrics.

## Testing

```bash
uv run pytest
```

## Architecture

*   `main.py`: CLI entry point (`fetch` / `analyze`).
*   `src/data_manager.py`: DuckDB cache (`get_cached`) and Yahoo Finance downloads (`fetch`).
*   `src/analyzer.py`: Contains the core investment logic (Gatekeeper, Scoring, Technicals).
*   `src/config.py`: Loads `config.yaml` once into `CFG`.
