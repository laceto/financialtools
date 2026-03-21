# Plan: Extend FundamentalTraderAssistant with 7 Metric Groups

## Context

`FundamentalTraderAssistant` currently computes 11 hardcoded financial metrics, scores them
1–5 against hardcoded thresholds, and rolls them into a sector-weighted composite score.
The goal is to expand coverage to 7 metric groups (liquidity, solvency, profitability,
efficiency, cashflow, growth, red-flag ratios) drawn from reference implementations provided
as standalone functions.

The outcome is a richer `evaluate()` dict that includes both the extended scored metrics
(feeding the composite score) and a separate unscored extended-metrics DataFrame covering
growth rates, working-capital efficiency chains, and red-flag ratios that don't fit a
simple 1–5 threshold.

---

## Architecture Decision: Scored vs Unscored Split

Not all new metrics are appropriate for the composite scoring pipeline.
Two criteria for "scored":
1. Has a universal numeric threshold (not context-dependent)
2. Returns a simple ratio, not a time-differential

| Group | Scored (→ `compute_metrics()`) | Unscored (→ `compute_extended_metrics()`) |
|---|---|---|
| Liquidity | `QuickRatio`, `CashRatio`, `WorkingCapitalRatio` | — |
| Solvency | `DebtRatio`, `EquityRatio`, `NetDebtToEBITDA`, `InterestCoverage` | — |
| Profitability | `ROIC` (gross/op/net/ROA/ROE already exist) | — |
| Efficiency | `AssetTurnover` | `ReceivablesTurnover`, `DSO`, `InventoryTurnover`, `DIO`, `PayablesTurnover`, `DPO`, `CCC` |
| Cash Flow | `OCFRatio`, `FCFMargin`, `CashConversion`, `CapexRatio` | — |
| Growth | — | `RevenueGrowth`, `NetIncomeGrowth`, `FCFGrowth` |
| Red Flags | — | `Accruals`, `DebtGrowth`, `Dilution`, `CapexToDepreciation` |

**New scored total: 13 metrics** (24 total after change)
**New unscored total: 14 metrics**

---

## Column Name Mapping (yfinance snake_case)

All columns are normalized by `__reshape_fin_data()` as `col.replace(' ', '_').lower()`.

| Needed by new metrics | Actual column name in `self.d` | Source statement |
|---|---|---|
| `stockholders_equity` | `common_stock_equity` | balance sheet |
| `net_income` | `net_income_common_stockholders` | income stmt |
| `interest_expense` | `interest_expense_non_operating` | income stmt (may be NaN) |
| `tax_rate_for_calcs` | `tax_rate_for_calcs` | income stmt (may be NaN) |
| `invested_capital` | `invested_capital` | balance sheet (may be NaN) |
| `receivables` | `accounts_receivable` | balance sheet |
| `payables` | `accounts_payable` | balance sheet |
| `inventory` | `inventory` | balance sheet |
| `working_capital` | `working_capital` | balance sheet derived |
| `net_debt` | `net_debt` | balance sheet derived |
| `cash_and_cash_equivalents` | `cash_and_cash_equivalents` | balance sheet |
| `ebit` | `ebit` | income stmt |
| `capital_expenditure` | `capital_expenditure` | cashflow |
| `depreciation_amortization_depletion` | `depreciation_amortization_depletion` | cashflow |
| `ordinary_shares_number` | `ordinary_shares_number` | balance sheet |
| `operating_cash_flow` | `operating_cash_flow` | cashflow (already in `raw_red_flags`) |

Columns that may be missing for some tickers (`interest_expense_non_operating`,
`tax_rate_for_calcs`, `invested_capital`) must be accessed via
`d.get(col, pd.Series(np.nan, index=d.index))` to prevent silent KeyError suppression
by the broad `except` in each compute method.

---

## Files to Modify

| File | Change |
|---|---|
| `financialtools/processor.py` | Extend `compute_metrics()`, `score_metric()`, add `compute_extended_metrics()`, update `evaluate()` and `_EMPTY_RESULT_KEYS` |
| `financialtools/config.py` | Add 13 new metric keys to every sector dict (20 in `sector_metric_weights` + 12 in `sec_sector_metric_weights` + `grouped_weights`) |

`wrappers.py` is **out of scope** — `export_financial_results()` will not export
`extended_metrics` in this change (can be added later).

---

## Step-by-Step Implementation Plan

### Step 1 — Extend `compute_metrics()` in `processor.py`

Add the 13 new scored metrics after the existing 11.
Use `d.get(col, pd.Series(np.nan, index=d.index))` for optional columns.
Append new column names to `metric_cols` list inside the method.
All names use CamelCase to match existing convention.

```python
# Liquidity additions
d["QuickRatio"] = self.safe_div(
    d["current_assets"] - d.get("inventory", pd.Series(np.nan, index=d.index)),
    d["current_liabilities"]
)
d["CashRatio"] = self.safe_div(
    d.get("cash_and_cash_equivalents", pd.Series(np.nan, index=d.index)),
    d["current_liabilities"]
)
d["WorkingCapitalRatio"] = self.safe_div(
    d.get("working_capital", pd.Series(np.nan, index=d.index)),
    d["current_assets"]
)

# Solvency additions
d["DebtRatio"] = self.safe_div(d["total_debt"], d["total_assets"])
d["EquityRatio"] = self.safe_div(d["common_stock_equity"], d["total_assets"])
d["NetDebtToEBITDA"] = self.safe_div(
    d.get("net_debt", pd.Series(np.nan, index=d.index)), d["ebitda"]
)
d["InterestCoverage"] = self.safe_div(
    d.get("ebit", pd.Series(np.nan, index=d.index)),
    d.get("interest_expense_non_operating", pd.Series(np.nan, index=d.index))
)

# Returns addition
_tax = d.get("tax_rate_for_calcs", pd.Series(np.nan, index=d.index))
_ic  = d.get("invested_capital",   pd.Series(np.nan, index=d.index))
d["ROIC"] = self.safe_div(
    d.get("ebit", pd.Series(np.nan, index=d.index)) * (1 - _tax), _ic
)

# Efficiency addition
d["AssetTurnover"] = self.safe_div(d["total_revenue"], d["total_assets"])

# Cash Flow additions
d["OCFRatio"] = self.safe_div(d["operating_cash_flow"], d["current_liabilities"])
d["FCFMargin"] = self.safe_div(d["free_cash_flow"], d["total_revenue"])
d["CashConversion"] = self.safe_div(
    d["operating_cash_flow"], d["net_income_common_stockholders"]
)
d["CapexRatio"] = self.safe_div(
    d.get("capital_expenditure", pd.Series(np.nan, index=d.index)),
    d["operating_cash_flow"]
)
```

### Step 2 — Add thresholds in `score_metric()`

Append 13 new entries to the `thresholds` dict.
`NetDebtToEBITDA`, `DebtRatio`, and `CapexRatio` use inverse scoring (lower is better).

```python
# Liquidity additions
"QuickRatio":           [0.5, 0.8, 1.0, 1.5],
"CashRatio":            [0.1, 0.2, 0.5, 1.0],
"WorkingCapitalRatio":  [0.05, 0.1, 0.2, 0.3],

# Solvency additions
"DebtRatio":            [0.2, 0.4, 0.6, 0.8],   # inverse: lower is better
"EquityRatio":          [0.2, 0.4, 0.6, 0.8],
"NetDebtToEBITDA":      [1.0, 2.0, 3.0, 5.0],   # inverse: lower is better
"InterestCoverage":     [1.5, 3.0, 5.0, 10.0],

# Returns addition
"ROIC":                 [0.05, 0.1, 0.15, 0.2],

# Efficiency addition
"AssetTurnover":        [0.3, 0.6, 1.0, 1.5],

# Cash Flow additions
"OCFRatio":             [0.1, 0.2, 0.4, 0.6],
"FCFMargin":            [0.02, 0.05, 0.1, 0.2],
"CashConversion":       [0.5, 0.8, 1.0, 1.2],
"CapexRatio":           [0.1, 0.2, 0.4, 0.6],   # inverse: lower is better
```

Add a `_INVERSE_METRICS` frozenset and update `score_row()` to check it:

```python
_INVERSE_METRICS = frozenset({"DebtToEquity", "DebtRatio", "NetDebtToEBITDA", "CapexRatio"})

def score_row(row):
    name, value = row['metrics'], row['value']
    if pd.isna(value):
        return 3
    if name in thresholds:
        score = np.digitize(value, thresholds[name]) + 1
        if name in _INVERSE_METRICS:
            return 6 - score
        return score
    return 3
```

### Step 3 — Update `config.py` sector weights

Add all 13 new metric keys to every sector dict.
**Exact dicts to update: `grouped_weights` (add new group), all 20 entries in
`sector_metric_weights`, all 12 entries in `sec_sector_metric_weights`.**

Add a new group to `grouped_weights`:
```python
"Extended Metrics": {
    "QuickRatio": 4, "CashRatio": 2, "WorkingCapitalRatio": 2,
    "DebtRatio": 4, "EquityRatio": 2, "NetDebtToEBITDA": 6, "InterestCoverage": 6,
    "ROIC": 8,
    "AssetTurnover": 4,
    "OCFRatio": 4, "FCFMargin": 4, "CashConversion": 4, "CapexRatio": 2,
}
```

For each sector dict, assign reasonable weights (sum of new keys ≈ 40–50 to preserve
relative importance of original 11 metrics). Finance and real-estate sectors that
zero-out `GrossMargin`/`CurrentRatio` need corresponding zeros for sector-inappropriate
new metrics (e.g., `QuickRatio`, `OCFRatio`, `NetDebtToEBITDA` for Finance).

### Step 4 — Update `SCORED_METRICS` constant

Append the 13 new names to the module-level list (documentation/alignment reference only).

### Step 5 — Add `compute_extended_metrics()` method

New method on `FundamentalTraderAssistant`. Key invariants:
- Sort `self.d` by `time` **before** `pct_change()` to ensure growth rates are
  chronologically correct.
- Return wide DataFrame: `ticker`, `time`, `sector` + all 14 unscored metric columns.
- Never mutate `self.d` — work on a copy.

```python
def compute_extended_metrics(self) -> pd.DataFrame:
    """
    Compute unscored efficiency, growth, and red-flag metrics.

    These metrics are NOT fed into the composite scoring pipeline because they
    are time-differential (pct_change) or derived chains (CCC) that lack universal
    thresholds. They are returned as a separate DataFrame via evaluate().

    Invariant: self.d is sorted by time before pct_change() to guarantee
    chronological ordering. The sort is applied to a copy — self.d is not mutated.
    """
    try:
        d = self.d.copy().sort_values("time").reset_index(drop=True)
        # ... efficiency chain, growth, red-flag ratios ...
        result_cols = [...]
        out = d[["ticker", "time"] + result_cols].copy()
        out["sector"] = self.sector
        return out
    except Exception as e:
        _logger.error(f"[{self.ticker}] compute_extended_metrics failed: {e}", exc_info=True)
        return pd.DataFrame()
```

### Step 6 — Update `evaluate()` and `_EMPTY_RESULT_KEYS`

1. Add `"extended_metrics"` to `_EMPTY_RESULT_KEYS` tuple.
2. Call `self.compute_extended_metrics()` in `evaluate()`.
3. Add `"extended_metrics": <result>` to the return dict.

### Step 7 — Write tests (`tests/test_processor.py`)

Create from scratch using a synthetic 3-row DataFrame (no network calls). Cover:

1. `compute_metrics()` produces all 24 expected columns
2. `compute_extended_metrics()` produces correct growth values (known pct_change inputs)
3. `compute_extended_metrics()` sorts by time before computing growth (input rows in
   reverse order → same result)
4. `score_metric()` returns expected score for each new threshold bucket (spot-check 3–4
   new metrics)
5. Inverse-scored metrics score correctly (high DebtRatio → low score)
6. `evaluate()` returns all 6 keys with non-empty DataFrames when given valid input

---

## Invariants and Failure Modes

| Invariant | Enforcement |
|---|---|
| Missing optional columns produce NaN metrics, not KeyError crashes | `d.get(col, pd.Series(np.nan, index=d.index))` at every optional access |
| Growth metrics are always in time order | `sort_values("time")` on copy before `pct_change()` |
| New scored metrics get weights in all sector dicts | Step 3 updates all 32 dicts; any miss produces a logged warning and NaN exclusion |
| `evaluate()` always returns all 6 keys | `_EMPTY_RESULT_KEYS` updated and `_empty_result()` covers new key |
| Inverse-scored metrics are explicitly listed | Named in `_INVERSE_METRICS` frozenset inside `score_metric()` |

---

## Current Status

Steps 1–6 are partially applied to `processor.py` (in-progress as of 2026-03-19).
`config.py` and tests have not been updated yet.

### Remaining work

- [ ] Step 3: Add 13 new metric keys to all sector dicts in `config.py`
- [ ] Step 7: Write `tests/test_processor.py`

---

## Verification

```bash
# Run tests
python -m unittest tests/test_processor.py -v

# Smoke test against real ticker (requires network + .env)
python -c "
from financialtools.processor import Downloader, FundamentalTraderAssistant
from financialtools.config import sector_metric_weights
import pandas as pd

d = Downloader.from_ticker('AAPL')
merged = d.get_merged_data()
weights = pd.DataFrame(
    list(sector_metric_weights['Technology Services'].items()),
    columns=['metrics', 'weights']
)
weights['sector'] = 'Technology Services'
fta = FundamentalTraderAssistant(merged, weights)
result = fta.evaluate()
for k, v in result.items():
    print(k, v.shape if not v.empty else 'EMPTY')
"
```

Expected output: all 6 keys print non-empty shapes; `metrics` DataFrame has 24 metric
columns; `extended_metrics` has 14 unscored columns + ticker/time/sector.
