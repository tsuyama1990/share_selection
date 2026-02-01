import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, Tuple
from .config import get_gatekeeper_config, get_scoring_config

# Load Configurations
GK = get_gatekeeper_config()
SC = get_scoring_config()

def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure the DataFrame columns (periods) are datetime objects and tz-naive.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame (financials or balance_sheet).

    Returns
    -------
    pd.DataFrame
        DataFrame with tz-naive datetime columns.
    """
    if df.empty:
        return df
    
    # Transpose financials/bs if needed (columns should be dates)
    if not isinstance(df.columns, pd.DatetimeIndex):
        try:
            df.columns = pd.to_datetime(df.columns)
        except Exception:
            pass
    
    # Convert tz-aware columns to naive
    if isinstance(df.columns, pd.DatetimeIndex) and df.columns.tz is not None:
         df.columns = df.columns.tz_localize(None)
         
    return df

def _ensure_history_index(df: pd.DataFrame) -> pd.DataFrame:
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

def get_fiscal_year_growth(financials: pd.DataFrame, years_back: int = 4) -> Tuple[Optional[float], Optional[float]]:
    """
    Calculate sales growth over N years (or fewer if data unavailable).
    Minimum 3 years of data required for meaningful growth calculation.

    Parameters
    ----------
    financials : pd.DataFrame
        Financials DataFrame containing 'Total Revenue'.
    years_back : int, optional
        Number of years to look back, by default 4.

    Returns
    -------
    Tuple[Optional[float], Optional[float]]
        (growth_rate, current_sales). Returns (None, None) if insufficient data.
    """
    try:
        sales = financials.loc['Total Revenue']
        if len(sales) == 0: 
            return None, None
        
        # Get current sales (latest period)
        current_sales = sales.iloc[0]
        if pd.isna(current_sales) or current_sales == 0:
            return None, None
        
        # Find the oldest valid (non-NaN, non-zero) sales data
        past_sales = None
        actual_years = 0
        
        for i in range(min(years_back, len(sales) - 1), 0, -1):
            candidate = sales.iloc[i]
            if not pd.isna(candidate) and candidate > 0:
                past_sales = candidate
                actual_years = i
                break
        
        # Require at least 3 years of data
        if past_sales is None or actual_years < 3:
            return None, None
        
        growth_rate = (current_sales / past_sales) - 1
        return growth_rate, current_sales
        
    except Exception:
        return None, None

def _check_gatekeeper(
    fast_info: Dict[str, Any], 
    bs: pd.DataFrame, 
    fin: pd.DataFrame, 
    cf: pd.DataFrame
) -> Optional[Dict[str, Any]]:
    """
    Check Gatekeeper rules (Equity Ratio, Operating Margin, PSR Cap, OCF > 0).

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

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with basic metrics if the stock passes criteria, else None.
    """
    res = {}
    
    # 1. Market Cap
    mcap = fast_info.get('market_cap')
    price = fast_info.get('last_price')
    if not mcap or mcap < 1e8:
        return None
    
    res['Current_Price'] = price
    res['Market_Cap'] = mcap
    res['Market_Cap(Billion)'] = round(mcap / 1e9, 2)

    # 2. Equity Ratio
    # Definition: Net Assets / Total Assets
    try:
        latest_bs = bs.iloc[:, 0]
        total_assets = latest_bs.get('Total Assets')
        
        # Priority: Consolidated > Parent-only
        total_equity = (
            latest_bs.get('Total Equity Gross Minority Interest') or 
            latest_bs.get('Stockholders Equity') or 
            latest_bs.get('Total Stockholder Equity')
        )
        
        if total_assets and total_equity:
            eq_ratio = total_equity / total_assets
            res['Equity_Ratio'] = round(eq_ratio * 100, 2)
            if eq_ratio < GK.get('equity_ratio_min', 0.40):
                return None
        else:
            return None
    except Exception:
        return None

    # 3. Operating Margin & PSR
    try:
        current_sales = fin.loc['Total Revenue'].iloc[0]
        op_income = fin.loc['Operating Income'].iloc[0]
        
        if current_sales:
            op_margin = op_income / current_sales
            res['Operating_Margin(%)'] = round(op_margin * 100, 2)
            if op_margin < GK.get('operating_margin_min', 0.10):
                return None
            
            # PSR Check
            psr = mcap / current_sales
            res['PSR'] = round(psr, 2)
            if psr > GK.get('psr_cap', 2.5):
                return None
        else:
            return None
    except Exception:
        return None

    # 4. Operating Cash Flow (OCF) Check
    try:
        if not cf.empty:
            latest_cf = cf.iloc[:, 0]
            
            # OCF
            ocf = latest_cf.get('Operating Cash Flow') or latest_cf.get('Total Cash From Operating Activities')
            if ocf is not None:
                res['Operating_Cash_Flow'] = ocf
                if ocf <= GK.get('operating_cash_flow_min', 0):
                    return None
            
            # Investing CF
            icf = latest_cf.get('Investing Cash Flow') or latest_cf.get('Total Cashflows From Investing Activities')
            if icf is not None:
                res['Investing_Cash_Flow'] = icf

            # Financing CF
            fcf = latest_cf.get('Financing Cash Flow') or latest_cf.get('Total Cash From Financing Activities')
            if fcf is not None:
                res['Financing_Cash_Flow'] = fcf
    except Exception:
        pass

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
    growth_rate, _ = get_fiscal_year_growth(fin, 4)
    if growth_rate is not None:
        result['Sales_Growth_4Y(%)'] = round(growth_rate * 100, 2)
        if growth_rate >= SC.get('sales_growth_threshold', 1.0):
            result['Score_Growth'] += SC.get('sales_growth_points', 3)

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
    if psr <= SC.get('psr_super_cheap', 0.5):
        result['Score_Value'] += SC.get('psr_cheap_points', 3)
    else:
        result['Score_Value'] += SC.get('psr_fair_points', 1)

    # 2. Cash Ratio & Net-Net
    try:
        total_cash = latest_bs.get('Cash And Cash Equivalents', 0)
        if market_cap > 0:
            cash_ratio = total_cash / market_cap
            result['Cash_to_MarketCap_Ratio'] = round(cash_ratio, 2)
            if cash_ratio >= 1.0:
                result['Score_Value'] += SC.get('net_net_bonus', 5)
                result['Recommendation_Type'] = 'NET-NET'
                result['Net_Net_Flag(T/F)'] = True
    except Exception:
         result['Cash_to_MarketCap_Ratio'] = None

    # 3. PBR
    pbr = info.get('priceToBook')
    if not pbr:
        try:
            total_equity = (
                latest_bs.get('Total Equity Gross Minority Interest') or
                latest_bs.get('Stockholders Equity') or 
                latest_bs.get('Total Stockholder Equity')
            )
            if total_equity and total_equity > 0:
                pbr = market_cap / total_equity
        except Exception:
            pass
    
    if pbr:
        result['PBR'] = round(pbr, 2)

    # 4. Dividend Score
    div = info.get('dividendYield')
    if div:
        result['Dividend_Yield(%)'] = round(div * 100, 2)
        if div >= SC.get('dividend_yield_target', 0.03):
            result['Score_Value'] += SC.get('dividend_points', 1)

    # 5. PER Growth
    f_pe = info.get('forwardPE')
    t_pe = info.get('trailingPE')
    if f_pe and t_pe:
        result['Forward_PE'] = round(f_pe, 2)
        result['Trailing_PE'] = round(t_pe, 2)
        if f_pe < t_pe:
            result['PE_Growth_Flag(T/F)'] = True
            result['Score_Value'] += SC.get('per_growth_points', 2)

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
    
    hist_monthly = _ensure_history_index(hist_monthly)
    
    if len(hist_monthly) >= SC.get('ma_long', 24):
        close = hist_monthly['Close']
        ma_s = close.rolling(SC.get('ma_short', 12)).mean().iloc[-1]
        ma_l = close.rolling(SC.get('ma_long', 24)).mean().iloc[-1]
        
        result['MA12'] = round(ma_s, 1)
        result['MA24'] = round(ma_l, 1)
        
        # Trend
        if current_price > ma_s > ma_l:
            result['Chart_Trend'] = 'Strong Bull'
            result['Score_Safety'] += SC.get('technical_points', 2)
        elif current_price > ma_s:
            result['Chart_Trend'] = 'Bull'
            result['Score_Safety'] += 1
        else:
            result['Chart_Trend'] = 'Bear'
    
    # Safety Buffer (Vs 2020 Low)
    corona = hist_monthly['2020-01-01':'2020-06-30']
    if not corona.empty:
        low = corona['Low'].min()
        if low > 0:
            diff = (current_price - low) / current_price * 100
            if abs(diff) < SC.get('safety_buffer_pct', 20):
                  result['Score_Safety'] += SC.get('safety_points', 2)

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
    fin = _ensure_datetime_index(data.get('financials', pd.DataFrame()))
    bs = _ensure_datetime_index(data.get('balance_sheet', pd.DataFrame()))
    cf = _ensure_datetime_index(data.get('cashflow', pd.DataFrame()))
    hist_monthly = _ensure_history_index(data.get('history_monthly', pd.DataFrame()))

    # 1. Gatekeeper Check
    gk_res = _check_gatekeeper(fast_info, bs, fin, cf)
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
        'Score_Safety': 0,
        # Metrics placeholders
        'PSR': None, 
        'PBR': None, 
        'Cash_to_MarketCap_Ratio': None, 
        'Dividend_Yield(%)': None, 
        'PE_Growth_Flag(T/F)': False,
        'Chart_Trend': '-', 
        'MA12': None, 
        'MA24': None
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
