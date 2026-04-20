"""evaluator.py — fundamental metrics compute and scoring layer.

Provides FundamentalMetricsEvaluator: computes financial ratios, scores them
against sector weights, detects red flags, and returns a structured result dict.

Depends on: exceptions, pandas, numpy only.
No yfinance calls — see downloader.py for data acquisition.
"""
import logging as _logging

import numpy as np
import pandas as pd

from financialtools.exceptions import EvaluationError

_logger = _logging.getLogger(__name__)


# Canonical empty result shape for evaluate() — all keys always present.
# Invariant: every key in the success return of evaluate() must appear here.
# IMPORTANT: Always return via _empty_result() — never _EMPTY_RESULT.copy(),
# which is a shallow copy and shares DataFrame objects across calls.
_EMPTY_RESULT_KEYS = (
    "metrics", "eval_metrics", "composite_scores",
    "raw_red_flags", "red_flags", "extended_metrics",
)


def _empty_result() -> dict:
    """Return a fresh dict of empty DataFrames with the canonical evaluate() shape."""
    return {k: pd.DataFrame() for k in _EMPTY_RESULT_KEYS}


def empty_result() -> dict:
    """Public factory — return a fresh empty evaluate() result dict.

    Use this instead of the private ``_empty_result`` wherever a fallback
    result is needed outside of ``evaluator.py``.  All six canonical keys are
    always present so callers can safely call ``result.get(key)`` without
    guarding for None.

    Returns
    -------
    dict
        ``{"metrics": DataFrame, "eval_metrics": DataFrame,
           "composite_scores": DataFrame, "raw_red_flags": DataFrame,
           "red_flags": DataFrame, "extended_metrics": DataFrame}``
        — all DataFrames are empty.
    """
    return _empty_result()


# Columns that compute_metrics() accesses with hard bracket notation.
# Any column absent from the input DataFrame is filled with np.nan so formulas
# produce NaN scores instead of raising KeyError.
# Two categories:
#   - Sector-conditional: banks / insurance structurally omit these
#   - Core: should always be present; guard against yfinance schema changes
# _fill_missing_cols() logs a single WARNING listing ALL absent columns before
# filling them, giving an actionable diff instead of an opaque EvaluationError.
_REQUIRED_METRIC_COLS: tuple = (
    # Sector-conditional (banks structurally omit these)
    "gross_profit",
    "operating_income",
    "ebitda",
    "current_assets",
    "current_liabilities",
    # Core — should always be present; guard against yfinance schema changes
    "total_revenue",
    "net_income_common_stockholders",
    "total_assets",
    "common_stock_equity",
    "free_cash_flow",
    "total_debt",
    "operating_cash_flow",
)

# Columns required by compute_valuation_metrics().
_REQUIRED_VALUATION_COLS: tuple = (
    "common_stock_equity",
    "free_cash_flow",
    "diluted_eps",
)

# Columns required by compute_extended_metrics() with hard bracket access.
_REQUIRED_EXTENDED_COLS: tuple = (
    "total_revenue",
    "net_income_common_stockholders",
    "free_cash_flow",
    "total_debt",
)

SCORED_METRICS: list = [
    # Original 11
    "GrossMargin",
    "OperatingMargin",
    "NetProfitMargin",
    "EBITDAMargin",
    "ROA",
    "ROE",
    "FCFToRevenue",
    "FCFYield",
    "FCFtoDebt",
    "DebtToEquity",
    "CurrentRatio",
    # Extended 13 (added by compute_metrics() expansion)
    "QuickRatio",
    "CashRatio",
    "WorkingCapitalRatio",
    "DebtRatio",
    "EquityRatio",
    "NetDebtToEBITDA",
    "InterestCoverage",
    "ROIC",
    "AssetTurnover",
    "OCFRatio",
    "FCFMargin",
    "CashConversion",
    "CapexRatio",
]


class FundamentalMetricsEvaluator:
    """Fundamental metrics evaluator and scorer.

    Computes financial ratios, scores them against sector weights, identifies
    red flags, and returns a structured dict via ``evaluate()``.

    Construct via ``FundamentalEvaluator`` (the high-level wrapper in
    ``wrappers.py``) rather than directly, unless you need lower-level control.
    """

    def __init__(self, data: pd.DataFrame, weights: pd.DataFrame):
        self.d = data
        self.metrics = pd.DataFrame()
        self.eval_metrics = pd.DataFrame()
        # Two distinct score attributes with different schemas — do NOT conflate:
        #   self.metric_scores  — long format, one row per (ticker, time, metric)
        #                         set by compute_scores()
        #   self.scores         — wide format, one row per (ticker, time)
        #                         with composite_score, set by evaluate()
        self.metric_scores = pd.DataFrame()
        self.scores = pd.DataFrame()
        self.weights = weights
        # Validate: exactly one non-null ticker — fail fast with a clear message.
        if 'ticker' not in data.columns or data.empty:
            raise EvaluationError(
                "data DataFrame is empty or missing a 'ticker' column — "
                "pass a non-empty merged DataFrame from Downloader.get_merged_data()."
            )
        tickers = data['ticker'].dropna().unique()
        if len(tickers) == 0:
            raise EvaluationError(
                "data DataFrame has no valid ticker values (empty or all-NaN ticker column)"
            )
        if len(tickers) > 1:
            raise EvaluationError(
                f"data contains multiple tickers {sorted(tickers.tolist())} — "
                "filter to a single ticker before calling FundamentalTraderAssistant"
            )
        self.ticker = tickers[0]

        # Validate: exactly one non-null sector in weights.
        sectors = weights['sector'].dropna().unique()
        if len(sectors) == 0:
            raise EvaluationError(
                "weights DataFrame has no valid sector values (empty or all-NaN sector column)"
            )
        if len(sectors) > 1:
            raise EvaluationError(
                f"weights contains multiple sectors {sorted(sectors.tolist())} — "
                "pass weights for a single sector"
            )
        self.sector = sectors[0]

    def safe_div(self, num, den) -> np.ndarray:
        try:
            num = pd.Series(num) if not isinstance(num, pd.Series) else num
            den = pd.Series(den) if not isinstance(den, pd.Series) else den
            return np.where((den != 0) & (den.notna()) & (num.notna()), num / den, np.nan)
        except Exception as e:
            _logger.error(f"[{self.ticker}] safe_div failed: {e}", exc_info=True)
            return np.full(len(num), np.nan)

    def _fill_missing_cols(self, d: pd.DataFrame, required: tuple) -> pd.DataFrame:
        """Fill any absent required columns with NaN and emit one consolidated warning.

        Emitting a single WARNING with the full column list gives an actionable diff
        instead of a later opaque KeyError or EvaluationError with no column context.
        """
        missing = [c for c in required if c not in d.columns]
        if missing:
            _logger.warning(
                "[%s] %d required column(s) absent — affected metrics will be NaN: %s. "
                "This may indicate a yfinance schema change or an unsupported ticker type.",
                self.ticker, len(missing), missing,
            )
            for col in missing:
                d[col] = np.nan
        return d

    def compute_valuation_metrics(self):
        try:
            d = self.d.copy()
            d = self._fill_missing_cols(d, _REQUIRED_VALUATION_COLS)

            if "sharesoutstanding" in d.columns:
                shares = d["sharesoutstanding"]
            else:
                _logger.warning(
                    f"[{self.ticker}] 'sharesoutstanding' not in data — "
                    "bvps and fcf_per_share will be NaN. "
                    "Merge sharesoutstanding from Downloader.get_info_data() before calling evaluate()."
                )
                shares = pd.Series(np.nan, index=d.index)

            _price  = d.get("currentprice", pd.Series(np.nan, index=d.index))
            _mktcap = d.get("marketcap",    pd.Series(np.nan, index=d.index))
            if "currentprice" not in d.columns:
                _logger.warning(
                    f"[{self.ticker}] 'currentprice' not in data — "
                    "P/E, P/B, P/FCF, EarningsYield will be NaN. "
                    "Merge currentprice from Downloader.get_info_data() before calling evaluate()."
                )
            if "marketcap" not in d.columns:
                _logger.warning(
                    f"[{self.ticker}] 'marketcap' not in data — "
                    "FCFYield will be NaN. "
                    "Merge marketcap from Downloader.get_info_data() before calling evaluate()."
                )

            d['bvps'] = self.safe_div(d["common_stock_equity"], shares)
            d['fcf_per_share'] = self.safe_div(d["free_cash_flow"], shares)
            d['eps'] = d['diluted_eps']

            d["P/E"] = self.safe_div(_price, d["eps"])
            d["P/B"] = self.safe_div(_price, d["bvps"])
            d["P/FCF"] = self.safe_div(_price, d["fcf_per_share"])
            d["EarningsYield"] = self.safe_div(d["eps"], _price)
            d["FCFYield"] = self.safe_div(d["free_cash_flow"], _mktcap)

            metric_cols = ["bvps", "fcf_per_share", "eps", "P/E",
                           "P/B", "P/FCF", "EarningsYield", "FCFYield"]

            d = d[["ticker", "time"] + metric_cols]
            d['sector'] = self.sector
            self.eval_metrics = d
            return d
        except Exception as e:
            _logger.error(f"[{self.ticker}] compute_valuation_metrics failed: {e}", exc_info=True)
            return pd.DataFrame()

    def compute_metrics(self):
        try:
            d = self.d.copy()

            # Fill any absent required columns with NaN before formula evaluation.
            # _fill_missing_cols() emits a single WARNING listing all missing columns,
            # so a yfinance schema change produces an actionable message rather than
            # an opaque KeyError swallowed by the except below.
            d = self._fill_missing_cols(d, _REQUIRED_METRIC_COLS)

            # ── Profitability Margins ─────────────────────────────────────────
            d["GrossMargin"] = self.safe_div(d["gross_profit"], d["total_revenue"])
            d["OperatingMargin"] = self.safe_div(d["operating_income"], d["total_revenue"])
            d["NetProfitMargin"] = self.safe_div(d["net_income_common_stockholders"], d["total_revenue"])
            d["EBITDAMargin"] = self.safe_div(d["ebitda"], d["total_revenue"])

            # ── Returns ───────────────────────────────────────────────────────
            d["ROA"] = self.safe_div(d["net_income_common_stockholders"], d["total_assets"])
            d["ROE"] = self.safe_div(d["net_income_common_stockholders"], d["common_stock_equity"])

            # ── Cash Flow Metrics ─────────────────────────────────────────────
            d["FCFToRevenue"] = self.safe_div(d["free_cash_flow"], d["total_revenue"])
            d["FCFYield"] = self.safe_div(
                d["free_cash_flow"],
                d.get("marketcap", pd.Series(np.nan, index=d.index)),
            )
            d["FCFtoDebt"] = self.safe_div(d["free_cash_flow"], d["total_debt"])

            # ── Leverage & Liquidity ──────────────────────────────────────────
            d["DebtToEquity"] = self.safe_div(d["total_debt"], d["common_stock_equity"])
            d["CurrentRatio"] = self.safe_div(d["current_assets"], d["current_liabilities"])

            # ── Liquidity (extended) ──────────────────────────────────────────
            d["QuickRatio"] = self.safe_div(
                d["current_assets"] - d.get("inventory", pd.Series(np.nan, index=d.index)),
                d["current_liabilities"],
            )
            d["CashRatio"] = self.safe_div(
                d.get("cash_and_cash_equivalents", pd.Series(np.nan, index=d.index)),
                d["current_liabilities"],
            )
            d["WorkingCapitalRatio"] = self.safe_div(
                d.get("working_capital", pd.Series(np.nan, index=d.index)),
                d["current_assets"],
            )

            # ── Solvency (extended) ───────────────────────────────────────────
            d["DebtRatio"] = self.safe_div(d["total_debt"], d["total_assets"])
            d["EquityRatio"] = self.safe_div(d["common_stock_equity"], d["total_assets"])
            d["NetDebtToEBITDA"] = self.safe_div(
                d.get("net_debt", pd.Series(np.nan, index=d.index)),
                d["ebitda"],
            )
            d["InterestCoverage"] = self.safe_div(
                d.get("ebit", pd.Series(np.nan, index=d.index)),
                d.get("interest_expense_non_operating", pd.Series(np.nan, index=d.index)),
            )

            # ── Returns: ROIC (extended) ──────────────────────────────────────
            _tax  = d.get("tax_rate_for_calcs", pd.Series(np.nan, index=d.index))
            _ic   = d.get("invested_capital",   pd.Series(np.nan, index=d.index))
            _ebit = d.get("ebit",               pd.Series(np.nan, index=d.index))
            d["ROIC"] = self.safe_div(_ebit * (1 - _tax), _ic)

            # ── Efficiency (extended) ─────────────────────────────────────────
            d["AssetTurnover"] = self.safe_div(d["total_revenue"], d["total_assets"])

            # ── Cash Flow (extended) ──────────────────────────────────────────
            d["OCFRatio"] = self.safe_div(d["operating_cash_flow"], d["current_liabilities"])
            d["FCFMargin"] = self.safe_div(d["free_cash_flow"], d["total_revenue"])
            d["CashConversion"] = self.safe_div(
                d["operating_cash_flow"],
                d["net_income_common_stockholders"],
            )
            d["CapexRatio"] = self.safe_div(
                d.get("capital_expenditure", pd.Series(np.nan, index=d.index)),
                d["operating_cash_flow"],
            )

            metric_cols = [
                # Original 11
                "GrossMargin", "OperatingMargin", "NetProfitMargin", "EBITDAMargin",
                "ROA", "ROE", "FCFToRevenue", "FCFYield", "FCFtoDebt",
                "DebtToEquity", "CurrentRatio",
                # Extended 13
                "QuickRatio", "CashRatio", "WorkingCapitalRatio",
                "DebtRatio", "EquityRatio", "NetDebtToEBITDA", "InterestCoverage",
                "ROIC",
                "AssetTurnover",
                "OCFRatio", "FCFMargin", "CashConversion", "CapexRatio",
            ]

            d = d[["ticker", "time"] + metric_cols]
            d['sector'] = self.sector
            self.metrics = d
            return d
        except Exception as e:
            _logger.error(f"[{self.ticker}] compute_metrics failed: {e}", exc_info=True)
            return pd.DataFrame()

    # Scoring thresholds — class constant, not rebuilt per call.
    # Four boundary values per metric map to scores 1–5 via np.digitize.
    _SCORE_THRESHOLDS: dict = {
        # Original 11
        "GrossMargin":         [0.2, 0.3, 0.4, 0.5],
        "OperatingMargin":     [0.05, 0.1, 0.15, 0.2],
        "NetProfitMargin":     [0.03, 0.07, 0.12, 0.2],
        "EBITDAMargin":        [0.1, 0.2, 0.3, 0.4],
        "ROA":                 [0.02, 0.05, 0.08, 0.12],
        "ROE":                 [0.05, 0.1, 0.15, 0.2],
        "FCFToRevenue":        [0.02, 0.05, 0.1, 0.2],
        "FCFYield":            [0.02, 0.04, 0.06, 0.1],
        # inverse: lower is better; negative values (negative equity) → score 1 via guard in score_row
        "DebtToEquity":        [0.5, 1.0, 1.5, 2.0],
        "CurrentRatio":        [1.0, 1.2, 1.5, 2.0],
        "FCFtoDebt":           [0.05, 0.1, 0.2, 0.3],
        # Liquidity (extended)
        "QuickRatio":          [0.5, 0.8, 1.0, 1.5],
        "CashRatio":           [0.1, 0.2, 0.5, 1.0],
        "WorkingCapitalRatio": [0.05, 0.1, 0.2, 0.3],
        # Solvency (extended)
        "DebtRatio":           [0.2, 0.4, 0.6, 0.8],   # inverse: lower is better
        "EquityRatio":         [0.2, 0.4, 0.6, 0.8],
        "NetDebtToEBITDA":     [1.0, 2.0, 3.0, 5.0],   # inverse: lower is better
        "InterestCoverage":    [1.5, 3.0, 5.0, 10.0],
        # Returns (extended)
        "ROIC":                [0.05, 0.1, 0.15, 0.2],
        # Efficiency (extended)
        "AssetTurnover":       [0.3, 0.6, 1.0, 1.5],
        # Cash Flow (extended)
        "OCFRatio":            [0.1, 0.2, 0.4, 0.6],
        "FCFMargin":           [0.02, 0.05, 0.1, 0.2],
        "CashConversion":      [0.5, 0.8, 1.0, 1.2],
        "CapexRatio":          [0.1, 0.2, 0.4, 0.6],   # inverse: lower is better
    }

    # Metrics where a lower value is better — score is inverted via 6 - score.
    _INVERSE_METRICS: frozenset = frozenset(
        {"DebtToEquity", "DebtRatio", "NetDebtToEBITDA", "CapexRatio"}
    )

    def _score_metric(self, df):
        """
        Apply trader-friendly scoring rules to a DataFrame with 'metrics' and 'value' columns.

        Returns a new DataFrame — does not mutate the input.

        Vectorized implementation: one np.digitize call per metric name rather than
        one Python function call per row.  This eliminates the row-by-row apply()
        overhead and removes the closure over self, making the method independently
        testable and picklable for ProcessPoolExecutor use.

        Scoring rules
        -------------
        - NaN value or unknown metric name → neutral score 3
        - DebtToEquity < 0 (negative book equity) → maximum risk score 1 (P1-1 guard)
        - Known metric → np.digitize against 4 thresholds → raw score 1–5
          inverse metrics (_INVERSE_METRICS) → 6 - raw_score
        """
        df = df.copy()
        # Default: score 3 (neutral) for NaN values and metrics not in _SCORE_THRESHOLDS.
        scores = pd.Series(3, index=df.index, dtype=np.int64)

        non_null = df['value'].notna()

        for metric_name, thresholds in self._SCORE_THRESHOLDS.items():
            mask = non_null & (df['metrics'] == metric_name)
            if not mask.any():
                continue
            raw = (np.digitize(df.loc[mask, 'value'].to_numpy(), thresholds) + 1).astype(np.int64)
            if metric_name in self._INVERSE_METRICS:
                raw = 6 - raw
            scores.loc[mask] = raw

        # P1-1 guard: negative book equity → negative D/E ratio → maximum risk.
        # Must run after the threshold loop so the inversion (above) cannot override it.
        neg_dte = non_null & (df['metrics'] == 'DebtToEquity') & (df['value'] < 0)
        scores.loc[neg_dte] = 1

        df['score'] = scores
        return df

    def compute_scores(self):
        try:
            if self.metrics is None or self.metrics.empty:
                self.compute_metrics()

            _id_vars = {"ticker", "time", "sector"}
            scored_cols = [c for c in self.metrics.columns if c not in _id_vars]
            df = self.metrics.melt(
                id_vars=["ticker", "time"],
                value_vars=scored_cols,
                var_name="metrics",
                value_name="value"
            )
            scored = self._score_metric(df)
            scored['sector'] = self.sector
            self.metric_scores = scored
            return scored
        except Exception as e:
            _logger.error(f"[{self.ticker}] compute_scores failed: {e}", exc_info=True)
            return pd.DataFrame()

    def raw_red_flags(self):
        try:
            _cols = ["ticker", "time", "free_cash_flow", "operating_cash_flow", "ebitda"]
            d = self.d.reindex(columns=_cols).copy()

            d["rrf_fcf"] = np.where(d["free_cash_flow"] < 0, "Negative Free Cash Flow", None)
            d["rrf_ocf"] = np.where(d["operating_cash_flow"] < 0, "Negative Operating Cash Flow", None)
            d["ebitdaVSocf"] = np.where(
                (d["ebitda"].notna()) & (d["operating_cash_flow"].notna()) &
                (d["ebitda"] > 2 * d["operating_cash_flow"]),
                "Earnings quality concern (EBITDA >> OCF)",
                None
            )

            d = d.melt(
                id_vars=["ticker", "time"],
                value_vars=["rrf_fcf", "rrf_ocf", "ebitdaVSocf"],
                var_name="metrics",
                value_name="red_flag"
            )

            return d[d["red_flag"].notna()]
        except Exception as e:
            _logger.error(f"[{self.ticker}] raw_red_flags failed: {e}", exc_info=True)
            return pd.DataFrame()

    def compute_extended_metrics(self) -> pd.DataFrame:
        """
        Compute unscored efficiency, growth, and red-flag metrics.

        These metrics are NOT fed into the composite scoring pipeline because they
        are either time-differential (pct_change) or derived chains (e.g., CCC)
        that lack universal thresholds appropriate for 1–5 scoring.

        Groups returned
        ---------------
        Efficiency chain  : ReceivablesTurnover, DSO, InventoryTurnover, DIO,
                            PayablesTurnover, DPO, CCC
        Growth            : RevenueGrowth, NetIncomeGrowth, FCFGrowth
        Red-flag ratios   : Accruals, DebtGrowth, Dilution, CapexToDepreciation

        Invariant: self.d is sorted by time on a copy before pct_change() to
        guarantee chronological ordering. self.d is never mutated.
        """
        try:
            d = self.d.copy().sort_values("time").reset_index(drop=True)
            d = self._fill_missing_cols(d, _REQUIRED_EXTENDED_COLS)

            _recv   = d.get("accounts_receivable",               pd.Series(np.nan, index=d.index))
            _inv    = d.get("inventory",                          pd.Series(np.nan, index=d.index))
            _pay    = d.get("accounts_payable",                   pd.Series(np.nan, index=d.index))
            _cogs   = d.get("cost_of_revenue",                    pd.Series(np.nan, index=d.index))
            _capex  = d.get("capital_expenditure",                pd.Series(np.nan, index=d.index))
            _da     = d.get("depreciation_amortization_depletion", pd.Series(np.nan, index=d.index))
            _shares = d.get("ordinary_shares_number",             pd.Series(np.nan, index=d.index))

            # ── Efficiency chain (working-capital turnover) ───────────────────
            d["ReceivablesTurnover"] = self.safe_div(d["total_revenue"], _recv)
            d["DSO"]                 = self.safe_div(_recv * 365, d["total_revenue"])
            d["InventoryTurnover"]   = self.safe_div(_cogs, _inv)
            d["DIO"]                 = self.safe_div(_inv * 365, _cogs)
            d["PayablesTurnover"]    = self.safe_div(_cogs, _pay)
            d["DPO"]                 = self.safe_div(_pay * 365, _cogs)
            d["CCC"] = np.where(
                pd.isna(d["DSO"]) | pd.isna(d["DIO"]) | pd.isna(d["DPO"]),
                np.nan,
                d["DSO"] + d["DIO"] - d["DPO"],
            )

            # ── Growth rates ──────────────────────────────────────────────────
            d["RevenueGrowth"]   = d["total_revenue"].pct_change()
            d["NetIncomeGrowth"] = d["net_income_common_stockholders"].pct_change()
            d["FCFGrowth"]       = d["free_cash_flow"].pct_change()

            # ── Red-flag ratios ───────────────────────────────────────────────
            d["Accruals"] = self.safe_div(
                d["net_income_common_stockholders"] - d["operating_cash_flow"],
                d["total_assets"],
            )
            d["DebtGrowth"] = d["total_debt"].pct_change()
            d["Dilution"]   = _shares.pct_change()
            d["CapexToDepreciation"] = self.safe_div(_capex.abs(), _da)

            result_cols = [
                "ReceivablesTurnover", "DSO", "InventoryTurnover", "DIO",
                "PayablesTurnover", "DPO", "CCC",
                "RevenueGrowth", "NetIncomeGrowth", "FCFGrowth",
                "Accruals", "DebtGrowth", "Dilution", "CapexToDepreciation",
            ]
            out = d[["ticker", "time"] + result_cols].copy()
            out["sector"] = self.sector
            return out

        except Exception as e:
            _logger.error(
                f"[{self.ticker}] compute_extended_metrics failed: {e}", exc_info=True
            )
            return pd.DataFrame()

    def _metrics_red_flags(self, df):
        """Add red flag names to a long-format DataFrame with 'metrics' and 'value' columns.

        Returns a new DataFrame — does not mutate the input.
        """
        df = df.copy()

        def single_metric_flag(row):
            metric, value = row["metrics"], row["value"]
            if pd.isna(value):
                return None

            if metric == "GrossMargin" and value < 0:
                return "Negative Gross Margin"
            if metric == "OperatingMargin" and value < 0:
                return "Negative Operating Margin"
            if metric == "NetProfitMargin" and value < 0:
                return "Negative Net Margin"
            if metric == "ROA" and value < 0:
                return "Negative ROA"
            if metric == "ROE" and value < 0:
                return "Negative ROE"
            if metric == "DebtToEquity" and value > 2:
                return "High Debt-to-Equity (>2)"
            if metric == "FCFtoDebt" and value < 0.05:
                return "Insufficient Free Cash Flow to cover debt"
            return None

        df["red_flag"] = df.apply(single_metric_flag, axis=1)
        df = df[df["red_flag"].notna()].reset_index(drop=True)

        return df

    @staticmethod
    def _compute_composite_scores(df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute per-ticker-per-year composite scores from a scored+weighted metrics DataFrame.

        Input columns required: ticker, time, sector, score, weights
        Output columns: sector, ticker, time, composite_score

        Formula: composite_score = sum(score * weights) / sum(weights)
        Invariant: weights come from sec_sector_metric_weights via the self.weights merge in evaluate().
        """
        df = df.copy()
        df["weighted_score"] = df["score"] * df["weights"]
        composite = (
            df.groupby(["ticker", "time", "sector"], as_index=False)
            .agg(
                total_weighted_score=("weighted_score", "sum"),
                total_weight=("weights", "sum"),
            )
        )
        composite["composite_score"] = composite["total_weighted_score"] / composite["total_weight"]
        return composite[["sector", "ticker", "time", "composite_score"]]

    def evaluate(self):
        """
        Evaluate financial metrics, compute scores, detect red flags, and return a summary.

        Returns
        -------
        dict with keys matching _EMPTY_RESULT_KEYS:
            "metrics": pd.DataFrame,
            "eval_metrics": pd.DataFrame,
            "composite_scores": pd.DataFrame,
            "raw_red_flags": pd.DataFrame,
            "red_flags": pd.DataFrame,
            "extended_metrics": pd.DataFrame

        Raises
        ------
        EvaluationError
            On any unrecoverable failure (empty metrics, unexpected exception).
        """
        try:
            m = self.compute_metrics()

            if m.empty:
                raise EvaluationError(
                    f"[{self.ticker}] compute_metrics() returned empty — "
                    "check logs for the underlying error."
                )

            ev = self.compute_valuation_metrics()
            d = self.raw_red_flags()

            _id_vars = {"ticker", "time", "sector"}
            scored_cols = [c for c in m.columns if c not in _id_vars]
            m_long = m.melt(
                id_vars=["ticker", "time"],
                value_vars=scored_cols,
                var_name="metrics",
                value_name="value"
            )

            s = self._score_metric(m_long)
            s = s.merge(self.weights, how="left", on="metrics")
            missing_weights = s[s["weights"].isna()]["metrics"].unique().tolist()
            if missing_weights:
                _logger.warning(
                    f"[{self.ticker}] Metrics missing weights after merge: {missing_weights}. "
                    "These metrics will be excluded from the composite score."
                )

            self.scores = self._compute_composite_scores(s)
            rf = self._metrics_red_flags(m_long)
            self.red_flags = rf[["ticker", "time", "metrics", "red_flag"]]
            ext = self.compute_extended_metrics()

            return {
                "metrics": self.metrics,
                "eval_metrics": self.eval_metrics,
                "composite_scores": self.scores,
                "raw_red_flags": d,
                "red_flags": self.red_flags,
                "extended_metrics": ext,
            }

        except EvaluationError:
            raise
        except Exception as e:
            _logger.error(
                "[%s] evaluate() failed unexpectedly: %s",
                getattr(self, "ticker", "?"), e, exc_info=True,
            )
            raise EvaluationError(
                f"[{getattr(self, 'ticker', '?')}] evaluate() failed: {e}"
            ) from e


class FundamentalTraderAssistant(FundamentalMetricsEvaluator):
    """Deprecated alias for ``FundamentalMetricsEvaluator``.

    Will be removed in a future release. Update imports to::

        from financialtools.processor import FundamentalMetricsEvaluator
    """

    def __init__(self, data: pd.DataFrame, weights: pd.DataFrame):
        import warnings
        warnings.warn(
            "FundamentalTraderAssistant is deprecated — use FundamentalMetricsEvaluator. "
            "The old name will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(data=data, weights=weights)
