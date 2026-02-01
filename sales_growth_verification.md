# Sales Growth Calculation - Verification Report

## Current Logic Analysis

### Code
```python
def get_fiscal_year_growth(financials: pd.DataFrame, years_back: int = 4):
    sales = financials.loc['Total Revenue']
    current_sales = sales.iloc[0]  # Latest (index 0)
    target_idx = min(years_back, len(sales) - 1)  # Problem here
    past_sales = sales.iloc[target_idx]
    return (current_sales / past_sales) - 1, current_sales
```

### Issue Identified

**Problem**: The logic assumes `iloc[years_back]` is exactly N years ago, but:
1. If company has only 3 years of data, `target_idx = min(4, 2) = 2` → compares 2 years, not 4
2. yfinance returns **5 periods** (TTM + 4 historical years), so:
   - `iloc[0]` = FY 2025 (latest)
   - `iloc[4]` = FY 2021 (4 years ago) ✓ Correct

**Actual behavior**: Works correctly for mature companies with 5+ years of data, but **underestimates growth period** for younger companies.

### Example: Toyota (7203.T)
- `iloc[0]`: FY2025 = ¥48.0T
- `iloc[4]`: FY2021 = NaN (missing)
- Result: Falls back to `iloc[3]` (FY2022 = ¥31.4T)
- **Calculated**: 3-year growth instead of 4-year

## Recommended Fix

### Option 1: Strict 4-Year Requirement
```python
def get_fiscal_year_growth(financials: pd.DataFrame, years_back: int = 4):
    sales = financials.loc['Total Revenue']
    if len(sales) < years_back + 1:  # Need at least 5 periods for 4-year growth
        return None, None  # Insufficient data
    
    current_sales = sales.iloc[0]
    past_sales = sales.iloc[years_back]  # Exactly 4 years ago
    
    if past_sales == 0 or np.isnan(past_sales):
        return None, current_sales
    return (current_sales / past_sales) - 1, current_sales
```

### Option 2: Flexible with Minimum Threshold
```python
def get_fiscal_year_growth(financials: pd.DataFrame, years_back: int = 4, min_years: int = 3):
    sales = financials.loc['Total Revenue']
    
    # Use as many years as available, but at least min_years
    actual_years = min(years_back, len(sales) - 1)
    if actual_years < min_years:
        return None, None
    
    current_sales = sales.iloc[0]
    past_sales = sales.iloc[actual_years]
    
    if past_sales == 0 or np.isnan(past_sales):
        return None, current_sales
    return (current_sales / past_sales) - 1, current_sales
```

## Recommendation
Use **Option 1** for consistency. All stocks should be evaluated on the same 4-year timeframe.
