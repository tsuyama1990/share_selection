"""Result vocabulary: row keys and shared values, defined once and imported everywhere else."""

from enum import StrEnum

TICKER = "Ticker"
NAME = "Name"
PRIORITY_RANK = "Priority_Rank"
STAGE2_CANDIDATE = "Stage2_Candidate"
NEXT_EARNINGS_DATE = "Next_Earnings_Date"
EARNINGS_PERIOD = "Earnings_Period"

EPS_Q_LATEST = "EPS_Q_Latest"
EPS_Q_LATEST_DATE = "EPS_Q_Latest_Date"
EPS_Q_PREV_YEAR = "EPS_Q_Prev_Year"
EPS_Q_YOY = "EPS_Q_YoY(%)"
OI_YOY = "OI_YoY(%)"
OP_MARGIN_CHANGE = "Op_Margin_Change(pt)"
IMPROVEMENT_CLASS = "Improvement_Class"
IMPROVEMENT_SOURCE = "Improvement_Source"
IMPROVEMENT_YIELD = "Improvement_Yield(%)"
QUALITY_FLAGS = "Quality_Flags"

CURRENT_PRICE = "Current_Price"
MARKET_CAP = "Market_Cap"
AVG_TURNOVER = "Avg_Turnover(M JPY)"
EQUITY_RATIO = "Equity_Ratio"
OPERATING_MARGIN = "Operating_Margin(%)"
PSR = "PSR"
OPERATING_CASH_FLOW = "Operating_Cash_Flow"
INVESTING_CASH_FLOW = "Investing_Cash_Flow"
FINANCING_CASH_FLOW = "Financing_Cash_Flow"

SALES_CAGR = "Sales_CAGR(%)"
SALES_GROWTH_YEARS = "Sales_Growth_Years"
CASH_TO_MARKET_CAP = "Cash_to_MarketCap_Ratio"
NET_CASH = "Net_Cash(Billion)"
REAL_PSR = "Real_PSR"
PBR = "PBR"
DIVIDEND_YIELD = "Dividend_Yield(%)"
CHART_TREND = "Chart_Trend"

CLASS_CLEAR = "clear"
CLASS_SIGNAL = "signal"
CLASS_NONE = "none"
UNKNOWN = "unknown"
CLASS_UNKNOWN = UNKNOWN
SOURCE_QUARTERLY = "quarterly"
SOURCE_ANNUAL = "annual"


class ReviewStatus(StrEnum):
    OK = "ok"
    NO_DOCUMENTS = "no_documents"
    LLM_FAILED = "llm_failed"
    BAD_JSON = "bad_json"


def ma(months: int) -> str:
    return f"MA{months}"


def downside_to_low(name: str) -> str:
    return f"Downside_to_{name}_Low(%)"
