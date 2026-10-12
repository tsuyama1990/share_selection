import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, Tuple
from .config import CFG

# Load Configurations
GK = CFG['gatekeeper']
SC = CFG['scoring']

def _to_naive_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure the history DataFrame index is datetime and tz-naive.

    Parameters
    ----------
    df : pd.DataFrame
        Stock history DataFrame.

    Returns
    -------
    pd.DataFrame
        DataFrame with tz-naive datetime index.
    """
    if df.empty:
        return df
        
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            pass
        
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
         df.index = df.index.tz_localize(None)
         
    return df

def _num(value: Any) -> Optional[float]:
    """
    Convert a value to float, treating None/NaN/non-numeric as missing.

    Parameters
    ----------
    value : Any
        Raw value from yfinance (may be None, NaN, or a number).

    Returns
    -------
    Optional[float]
        The value as float, or None if missing.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(value) else value

def _first_valid(row: pd.Series, keys: Tuple[str, ...]) -> Optional[float]:
    """
    Return the first non-missing value among keys.

    Unlike ``a or b``, a NaN in an earlier key does not shadow later keys.

    Parameters
    ----------
    row : pd.Series
        A single period of a financial statement.
    keys : Tuple[str, ...]
        Line item names in priority order.

    Returns
    -------
    Optional[float]
        The first valid value, or None if all are missing.
    """
    for key in keys:
        value = _num(row.get(key))
        if value is not None:
            return value
    return None

# Japanese equity ratio (自己資本比率) excludes non-controlling interests,
# so the parent's equity comes first.
EQUITY_KEYS = ('Stockholders Equity', 'Total Stockholder Equity', 'Total Equity Gross Minority Interest')
OCF_KEYS = ('Operating Cash Flow', 'Total Cash From Operating Activities')
ICF_KEYS = ('Investing Cash Flow', 'Total Cashflows From Investing Activities')
FCF_KEYS = ('Financing Cash Flow', 'Total Cash From Financing Activities')

def _latest_valid_period(df: pd.DataFrame, keys: Tuple[str, ...]) -> Optional[int]:
    """
    Position of the most recent period where all keys have values.

    yfinance sometimes adds a column for a fiscal year that has not been
    reported yet (all NaN); that column is skipped.

    Parameters
    ----------
    df : pd.DataFrame
        Financial statement (latest period first).
    keys : Tuple[str, ...]
        Line items that must all be present.

    Returns
    -------
    Optional[int]
        Column position, or None if no period has all keys.
    """
    if not set(keys) <= set(df.index):
        return None
    for i in range(df.shape[1]):
        if all(_num(df[df.columns[i]].get(key)) is not None for key in keys):
            return i
    return None

def get_sales_cagr(
    financials: pd.DataFrame,
    years_back: int = 4,
    min_years: int = 3
) -> Tuple[Optional[float], Optional[int]]:
    """
    Calculate annualized sales growth (CAGR) over up to N years.

    yfinance usually returns 4-5 annual periods and the oldest is often NaN,
    so the span is the oldest valid period within ``years_back``. Annualizing
    makes 3-year and 4-year spans comparable.

    Parameters
    ----------
    financials : pd.DataFrame
        Financials DataFrame containing 'Total Revenue' (latest period first).
    years_back : int, optional
        Maximum number of years to look back, by default 4.
    min_years : int, optional
        Minimum span required, by default 3.

    Returns
    -------
    Tuple[Optional[float], Optional[int]]
        (cagr, years). Returns (None, None) if insufficient data.
    """
    latest = _latest_valid_period(financials, ('Total Revenue',))
    if latest is None:
        return None, None
    sales = financials.loc['Total Revenue'].iloc[latest:]

    current_sales = _num(sales.iloc[0])
    if current_sales is None or current_sales <= 0:
        return None, None

    for years in range(min(years_back, len(sales) - 1), min_years - 1, -1):
        past_sales = _num(sales.iloc[years])
        if past_sales is not None and past_sales > 0:
            cagr = (current_sales / past_sales) ** (1 / years) - 1
            return cagr, years

    return None, None

def _avg_turnover(hist_daily: Optional[pd.DataFrame], days: int = 60) -> Optional[float]:
    """
    Average daily trading value (Close x Volume) over the last N sessions.

    Parameters
    ----------
    hist_daily : Optional[pd.DataFrame]
        Daily history with 'Close' and 'Volume' columns.
    days : int, optional
        Number of recent sessions to average, by default 60.

    Returns
    -------
    Optional[float]
        Average daily turnover in JPY, or None if unavailable.
    """
    if hist_daily is None or hist_daily.empty or not {'Close', 'Volume'} <= set(hist_daily.columns):
        return None
    turnover = (hist_daily['Close'] * hist_daily['Volume']).dropna().tail(days)
    return _num(turnover.mean()) if len(turnover) else None

def _check_gatekeeper(
    fast_info: Dict[str, Any],
    bs: pd.DataFrame,
    fin: pd.DataFrame,
    cf: pd.DataFrame,
    hist_daily: Optional[pd.DataFrame] = None
) -> Optional[Dict[str, Any]]:
    """
    Check Gatekeeper rules (Market Cap, Liquidity, Equity Ratio,
    Operating Margin, PSR Cap, OCF > 0).

    A metric that a rule depends on but cannot be computed (missing or NaN)
    fails the rule, so incomplete data never slips through.

    Parameters
    ----------
    fast_info : Dict[str, Any]
        Dictionary containing market_cap and last_price.
    bs : pd.DataFrame
        Balance Sheet DataFrame.
    fin : pd.DataFrame
        Financials DataFrame.
    cf : pd.DataFrame
        Cashflow DataFrame.
    hist_daily : Optional[pd.DataFrame], optional
        Daily history used for the liquidity check, by default None.

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with basic metrics if the stock passes criteria, else None.
    """
    res = {}

    # 1. Market Cap
    mcap = _num(fast_info.get('market_cap'))
    if mcap is None or mcap < GK['market_cap_min']:
        return None

    res['Current_Price'] = _num(fast_info.get('last_price'))
    res['Market_Cap'] = mcap
    res['Market_Cap(Billion)'] = round(mcap / 1e9, 2)

    # 2. Liquidity (average daily trading value)
    turnover = _avg_turnover(hist_daily)
    res['Avg_Turnover_60D(M JPY)'] = round(turnover / 1e6, 1) if turnover is not None else None
    turnover_min = GK['turnover_min']
    if turnover_min > 0 and (turnover is None or turnover < turnover_min):
        return None

    # 3. Equity Ratio
    # Definition: Stockholders' Equity / Total Assets
    if bs.empty:
        return None
    latest_bs = bs.iloc[:, 0]
    total_assets = _num(latest_bs.get('Total Assets'))
    total_equity = _first_valid(latest_bs, EQUITY_KEYS)
    if total_assets is None or total_assets <= 0 or total_equity is None:
        return None

    eq_ratio = total_equity / total_assets
    res['Equity_Ratio'] = round(eq_ratio * 100, 2)
    if eq_ratio < GK['equity_ratio_min']:
        return None

    # 4. Operating Margin & PSR
    latest = _latest_valid_period(fin, ('Total Revenue', 'Operating Income'))
    if latest is None:
        return None
    current_sales = _num(fin.loc['Total Revenue'].iloc[latest])
    op_income = _num(fin.loc['Operating Income'].iloc[latest])
    if current_sales <= 0:
        return None

    op_margin = op_income / current_sales
    res['Operating_Margin(%)'] = round(op_margin * 100, 2)
    if op_margin < GK['operating_margin_min']:
        return None

    psr = mcap / current_sales
    res['PSR'] = round(psr, 2)
    if psr > GK['psr_cap']:
        return None

    # 5. Operating Cash Flow (OCF) Check
    if cf.empty:
        return None
    latest_cf = cf.iloc[:, 0]
    ocf = _first_valid(latest_cf, OCF_KEYS)
    if ocf is None or ocf <= GK['operating_cash_flow_min']:
        return None

    res['Operating_Cash_Flow'] = ocf
    res['Investing_Cash_Flow'] = _first_valid(latest_cf, ICF_KEYS)
    res['Financing_Cash_Flow'] = _first_valid(latest_cf, FCF_KEYS)

    return res

def _score_growth(fin: pd.DataFrame, result: Dict[str, Any]):
    """
    Calculate Growth Logic and update result dictionary.

    Parameters
    ----------
    fin : pd.DataFrame
        Financials DataFrame.
    result : Dict[str, Any]
        Result dictionary to update.
    """
    cagr, years = get_sales_cagr(fin, 4)
    if cagr is not None:
        result['Sales_CAGR(%)'] = round(cagr * 100, 2)
        result['Sales_Growth_Years'] = years
        if cagr >= SC['sales_cagr_threshold']:
            result['Score_Growth'] += SC['sales_growth_points']

def _score_value(
    info: Dict[str, Any], 
    bs: pd.DataFrame, 
    market_cap: float, 
    psr: float, 
    result: Dict[str, Any]
):
    """
    Calculate Value Logic (PSR, Cash, PBR, Dividend, PER) and update result.

    Parameters
    ----------
    info : Dict[str, Any]
        Stock info dictionary.
    bs : pd.DataFrame
        Balance Sheet DataFrame.
    market_cap : float
        Market capitalization.
    psr : float
        Price-to-Sales Ratio.
    result : Dict[str, Any]
        Result dictionary to update.
    """
    latest_bs = bs.iloc[:, 0]
    
    # 1. PSR Score
    if psr <= SC['psr_super_cheap']:
        result['Score_Value'] += SC['psr_cheap_points']
    else:
        result['Score_Value'] += SC['psr_fair_points']

    # 2. Cash Ratio & Net-Net
    total_cash = _num(latest_bs.get('Cash And Cash Equivalents'))
    if total_cash is not None and market_cap > 0:
        cash_ratio = total_cash / market_cap
        result['Cash_to_MarketCap_Ratio'] = round(cash_ratio, 2)
        if cash_ratio >= 1.0:
            result['Score_Value'] += SC['net_net_bonus']
            result['Recommendation_Type'] = 'NET-NET'
            result['Net_Net_Flag(T/F)'] = True

    # 3. PBR
    pbr = _num(info.get('priceToBook'))
    if pbr is None:
        total_equity = _first_valid(latest_bs, EQUITY_KEYS)
        if total_equity is not None and total_equity > 0:
            pbr = market_cap / total_equity

    if pbr is not None:
        result['PBR'] = round(pbr, 2)

    # 4. Dividend Score
    # trailingAnnualDividendYield is a fraction (0.03 = 3%), while yfinance's
    # dividendYield is already in percent (3.0 = 3%).
    div = _num(info.get('trailingAnnualDividendYield'))
    if div is None:
        div_pct = _num(info.get('dividendYield'))
        div = div_pct / 100 if div_pct is not None else None
    if div is not None:
        result['Dividend_Yield(%)'] = round(div * 100, 2)
        if div >= SC['dividend_yield_target']:
            result['Score_Value'] += SC['dividend_points']

    # 5. PER Growth
    f_pe = _num(info.get('forwardPE'))
    t_pe = _num(info.get('trailingPE'))
    if f_pe is not None and t_pe is not None and f_pe > 0 and t_pe > 0:
        result['Forward_PE'] = round(f_pe, 2)
        result['Trailing_PE'] = round(t_pe, 2)
        if f_pe < t_pe:
            result['PE_Growth_Flag(T/F)'] = True
            result['Score_Value'] += SC['per_growth_points']

def _score_technical(hist_monthly: pd.DataFrame, current_price: float, result: Dict[str, Any]):
    """
    Calculate Technical Logic (MA12, MA24, Trend) and update result.

    Parameters
    ----------
    hist_monthly : pd.DataFrame
        Monthly history DataFrame.
    current_price : float
        Current stock price.
    result : Dict[str, Any]
        Result dictionary to update.
    """
    if hist_monthly is None or hist_monthly.empty:
        return
    
    if len(hist_monthly) >= SC['ma_long']:
        close = hist_monthly['Close']
        ma_s = close.rolling(SC['ma_short']).mean().iloc[-1]
        ma_l = close.rolling(SC['ma_long']).mean().iloc[-1]
        
        result['MA12'] = round(ma_s, 1)
        result['MA24'] = round(ma_l, 1)
        
        # Trend
        if current_price > ma_s > ma_l:
            result['Chart_Trend'] = 'Strong Bull'
            result['Score_Safety'] += SC['technical_points']
        elif current_price > ma_s:
            result['Chart_Trend'] = 'Bull'
            result['Score_Safety'] += 1
        else:
            result['Chart_Trend'] = 'Bear'

def analyze_stock_data(ticker_symbol: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Main analysis entry point. Conducts Gatekeeper checks and Scoring.

    Parameters
    ----------
    ticker_symbol : str
        Ticker symbol (e.g., '7203.T').
    data : Dict[str, Any]
        Dictionary containing stock data (info, fast_info, financials, etc.).

    Returns
    -------
    Optional[Dict[str, Any]]
        Analysis result dictionary if the stock passes Gatekeeper, else None.
    """
    if not data:
        return None
    
    # Unpack Data
    info = data.get('info', {})
    fast_info = data.get('fast_info', {})
    fin = data.get('financials', pd.DataFrame())
    bs = data.get('balance_sheet', pd.DataFrame())
    cf = data.get('cashflow', pd.DataFrame())
    hist_daily = _to_naive_datetime_index(data.get('history', pd.DataFrame()))
    hist_monthly = _to_naive_datetime_index(data.get('history_monthly', pd.DataFrame()))

    # 1. Gatekeeper Check
    gk_res = _check_gatekeeper(fast_info, bs, fin, cf, hist_daily)
    if not gk_res:
        return None
    
    # Initialize Result Dictionary
    result = {
        'Ticker': ticker_symbol,
        'Name': info.get('longName', ticker_symbol),
        'Total_Score': 0,
        'Recommendation_Type': 'Watch',
        'Score_Growth': 0, 
        'Score_Value': 0, 
        'Score_Safety': 0
    }
    result.update(gk_res) # Merge basic metrics

    # 2. Scoring
    _score_growth(fin, result)
    _score_value(info, bs, result['Market_Cap'], result['PSR'], result)
    _score_technical(hist_monthly, result['Current_Price'], result)

    # 3. Total & Recommendation
    result['Total_Score'] = result['Score_Growth'] + result['Score_Value'] + result['Score_Safety']
    
    if result.get('Recommendation_Type') != 'NET-NET':
        if result['Score_Growth'] >= 3: 
            result['Recommendation_Type'] = 'Quality Growth'
        elif result['Score_Value'] >= 4: 
            result['Recommendation_Type'] = 'Quality Value'
        else:
            result['Recommendation_Type'] = 'Watch'

    return result
