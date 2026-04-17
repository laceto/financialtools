import yfinance as yf
import os
import pandas as pd
from typing import Dict, Any, List
from financialtools.exceptions import DownloadError, EvaluationError
import numpy as np
import logging as _logging

# Module-level logger — defined here (before all class bodies) so every method
# can reference _logger at call time without an ordering hazard.
_logger = _logging.getLogger(__name__)


# RateLimiter moved to utils.py (M9 fix — generic threading utility has no
# financial domain logic; see financialtools/utils.py for the implementation).
# Re-exported here so existing imports of the form
#   from financialtools.processor import RateLimiter
# continue to work without change.
from financialtools.utils import RateLimiter  # noqa: F401  (re-export)


class Downloader:
    def __init__(self, ticker, _from_factory: bool = False):
        """Internal constructor — use ``Downloader.from_ticker(ticker)`` instead.

        Direct instantiation leaves all financial data as None, causing silent
        empty-DataFrame returns from ``get_merged_data()`` and all metric methods.
        """
        if not _from_factory:
            raise TypeError(
                "Use Downloader.from_ticker(ticker) to construct a Downloader. "
                "Direct instantiation leaves financial data unloaded, which causes "
                "silent empty-DataFrame returns from get_merged_data() and evaluate()."
            )
        self.ticker = ticker
        self._balance_sheet = None
        self._income_stmt = None
        self._cashflow = None
        self._info = None

    @classmethod
    def from_ticker(cls, ticker):
        """Download and reshape all financial data for one ticker.

        Returns
        -------
        Downloader
            Fully populated instance with ``_balance_sheet``, ``_income_stmt``,
            ``_cashflow``, and ``_info`` set.

        Raises
        ------
        DownloadError
            If yfinance raises any exception during data retrieval or reshaping.
            Callers that need a soft-failure path should catch ``DownloadError``
            explicitly — do **not** rely on an empty ``Downloader`` being returned.

        Note
        ----
        This method never returns a ``Downloader`` with ``None`` internals.
        Previously it returned ``cls(ticker)`` on failure (S4 fix), which was
        indistinguishable from a valid empty-data ticker and caused silent
        downstream errors in ``get_merged_data()`` and metric computation.
        """
        import yfinance as yf

        try:
            t = yf.Ticker(ticker)
            d = cls(ticker, _from_factory=True)

            # raw data
            d._balance_sheet = cls.__reshape_fin_data(
                t.balance_sheet.reset_index().assign(ticker=ticker, docs="balance_sheet")
            )
            d._income_stmt = cls.__reshape_fin_data(
                t.income_stmt.reset_index().assign(ticker=ticker, docs="income_stmt")
            )
            d._cashflow = cls.__reshape_fin_data(
                t.cashflow.reset_index().assign(ticker=ticker, docs="cashflow")
            )

            df_info = pd.DataFrame(list(t.info.items()), columns=["key", "value"])
            # df_info = df_info[df_info["key"].str.contains("marketCap|beta|industry|industryDisp|industryKey|longBusinessSummary|longName|sector|sectorDisp|sectorKey|website",
            #                                case=True, na=False)]
            df_info.insert(0, "ticker", ticker)
            df_info = df_info.pivot(index=["ticker"], columns='key', values='value').reset_index()
            # df_info = df_info.pivot(index=["ticker"], columns='key', values='value')
            d._info = df_info

            return d

        except Exception as e:
            _logger.error(f"[{ticker}] from_ticker failed: {e}", exc_info=True)
            raise DownloadError(f"[{ticker}] download failed: {e}") from e
            
    # @staticmethod
    # def __format_fin_data(ticker: str, data_type: str, df: pd.DataFrame) -> pd.DataFrame:
    #     if df is None or df.empty:
    #         return pd.DataFrame()
    #     df = df.reset_index()
    #     df["ticker"] = ticker
    #     df["docs"] = data_type
    #     return df


    @staticmethod
    def __reshape_fin_data(df: pd.DataFrame) -> pd.DataFrame:
        """
        Reshape financial data DataFrame to have 'ticker', 'time', and metric columns.

        Args:
            df: Financial data DataFrame from yfinance (e.g., balance sheet).
            ticker: Ticker symbol (str).

        Returns:
            pd.DataFrame with columns 'ticker', 'time', and financial metrics, or empty on failure.
        """
        if df.empty:
            return df
        try:
            pivot_vars = ["index", "ticker", "docs"]
            value_vars = [c for c in df.columns if c not in pivot_vars]
            df = df.melt(id_vars=pivot_vars, value_vars=value_vars,
                         var_name="time", value_name="value")
            df = df.pivot_table(index=["ticker", "docs", "time"],
                                columns="index", values="value").reset_index()
            df.columns = [col.replace(' ', '_').lower() for col in df.columns]
            return df
        except Exception as e:
            print(f"Error reshaping financial data: {e}")
            return pd.DataFrame()
    
    def get_info_data(self) -> pd.DataFrame:
        """
        Retrieve stock info for the ticker.

        Returns:
            pd.DataFrame with filtered stock info (e.g., marketCap, forwardPE) or empty DataFrame if unavailable.
        """
        if self._info is None or self._info.empty:
            return pd.DataFrame()
        return self._info
    
    # Market-data columns pulled from _info and broadcast across all time periods.
    # Keeping this list here (not in compute_valuation_metrics) makes it the single
    # source of truth for what get_merged_data() enriches.
    _MARKET_COLS = ("marketcap", "currentprice", "sharesoutstanding")

    def get_merged_data(self) -> pd.DataFrame:
        """
        Merge balance sheet, income statement, and cash flow data for a single ticker,
        then broadcast market-data columns (marketcap, currentprice, sharesoutstanding)
        from _info across all time periods.

        Callers no longer need to manually call get_info_data() and merge — the returned
        DataFrame is fully enriched and ready for FundamentalTraderAssistant.

        Returns pd.DataFrame() on failure; never raises.
        """
        try:
            dfs = [self._balance_sheet, self._cashflow, self._income_stmt]
            # Ensure all are non-empty and have required columns
            dfs = [df for df in dfs if isinstance(df, pd.DataFrame) and not df.empty]
            if len(dfs) < 2:
                return pd.DataFrame()

            # Merge financial statements on (ticker, time).
            merged = dfs[0]
            for df in dfs[1:]:
                merged = merged.merge(df, how="left", on=["ticker", "time"])

            if merged.empty:
                return pd.DataFrame()

            # Enrich with market-data columns from _info (marketcap, currentprice,
            # sharesoutstanding). Columns arrive in yfinance camelCase — lowercase them
            # to match the snake_case convention used throughout this module.
            if self._info is not None and not self._info.empty:
                info_lower = self._info.rename(columns=str.lower)
                available  = [c for c in self._MARKET_COLS if c in info_lower.columns]
                if available:
                    market_row = info_lower[["ticker"] + available]
                    merged = merged.merge(market_row, on="ticker", how="left")

            return merged

        except Exception as e:
            _logger.error(f"[{self.ticker}] get_merged_data failed: {e}", exc_info=True)
            return pd.DataFrame()

    @classmethod
    def combine_merged_data(cls, downloaders: List['Downloader']) -> pd.DataFrame:
        """
        Combine merged financial data from multiple Downloader instances.
        """
        try:
            dfs = []
            for d in downloaders:
                df = d.get_merged_data()
                if not df.empty:
                    dfs.append(df)
                else:
                    print(f"No merged data for {d.ticker}")

            if not dfs:
                return pd.DataFrame()

            combined = pd.concat(dfs, ignore_index=True)
            combined = combined.reindex(columns=combined.columns, fill_value=pd.NA)
            return combined

        except Exception as e:
            tickers = [d.ticker for d in downloaders]
            _logger.error(f"combine_merged_data failed for {tickers}: {e}", exc_info=True)
            return pd.DataFrame()


    @classmethod
    def combine_info_data(cls, downloaders: List['Downloader']) -> pd.DataFrame:
        """
        Combine merged financial data from multiple Downloader instances.
        """
        try:
            dfs = []
            for d in downloaders:
                df = d.get_info_data()
                if not df.empty:
                    dfs.append(df)
                else:
                    print(f"No merged data for {d.ticker}")

            if not dfs:
                return pd.DataFrame()

            combined = pd.concat(dfs, ignore_index=True)
            combined = combined.reindex(columns=combined.columns, fill_value=pd.NA)
            return combined

        except Exception as e:
            tickers = [d.ticker for d in downloaders]
            _logger.error(f"combine_info_data failed for {tickers}: {e}", exc_info=True)
            return pd.DataFrame()

    @classmethod
    def stream_download(
        cls,
        tickers: list[str],
        limiter: "RateLimiter",
        out_dir: str = "financial_data",
    ):
        """Stream tickers one by one, saving each to Parquet as soon as ready.

        Yields each successfully downloaded ``Downloader`` instance.

        Note: ``out_dir`` is relative to the caller's working directory, not the
        package root. Pass an absolute path (e.g. ``str(Path.cwd() / "data")``) if
        you need deterministic output placement from notebooks or scripts.
        """
        import os
        import pandas as pd

        os.makedirs(out_dir, exist_ok=True)

        for t in tickers:
            limiter.acquire()
            try:
                d = cls.from_ticker(t)

                tables = {
                    "merged_data": d.get_merged_data(),
                    "info": d.get_info_data()
                }

                for name, df in tables.items():
                    try:
                        if df is not None and not df.empty:
                            path = os.path.join(out_dir, f"{t}_{name}.parquet")
                            df.to_parquet(path)
                    except Exception as e:
                        _logger.error(f"[{t}] Parquet write failed for '{name}': {e}")

                # Optional JSON save block
                # try:
                #     if d._info:
                #         info_path = os.path.join(out_dir, f"{t}_info.json")
                #         pd.Series(d._info).to_json(info_path, indent=2)
                # except:
                #     pass

                print(f"Saved {t} data to {out_dir}")
                yield d

            except Exception as e:
                _logger.error(f"[{t}] Download failed: {e}", exc_info=True)




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


# Reference list of metric column names produced by compute_metrics().
# Used as documentation and for score_metric() threshold key alignment.
# evaluate() and compute_scores() derive value_vars dynamically from compute_metrics()
# output columns so that adding a new metric to compute_metrics() is automatically scored.
# Columns that compute_metrics() accesses with hard bracket notation.
# Financial-sector tickers (banks, insurance) structurally omit some of these.
# compute_metrics() fills any absent column with np.nan so formulas that use them
# produce NaN scores instead of raising KeyError.
_REQUIRED_METRIC_COLS: tuple = (
    "gross_profit",       # absent for banks (no COGS)
    "operating_income",   # absent for banks (use pretax_income instead in Option B)
    "ebitda",             # absent for banks
    "current_assets",     # absent for banks (different BS layout)
    "current_liabilities",# absent for banks
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
        # self.weights = get_sector_weights(self.sector)


    def safe_div(self, num, den):
        try:
            return np.where((den != 0) & (den.notna()) & (num.notna()), num / den, np.nan)
        except Exception as e:
            _logger.error(f"[{self.ticker}] safe_div failed: {e}", exc_info=True)
            return pd.Series([np.nan] * len(num))

    def compute_valuation_metrics(self):
        try:
            d = self.d.copy()

            # sharesoutstanding is not in the merged financial statements — it comes from
            # t.info ("sharesOutstanding"), which callers must merge in before constructing
            # FundamentalTraderAssistant. Fall back to a NaN series if absent so that
            # bvps/fcf_per_share are NaN rather than crashing the whole method.
            if "sharesoutstanding" in d.columns:
                shares = d["sharesoutstanding"]
            else:
                _logger.warning(
                    f"[{self.ticker}] 'sharesoutstanding' not in data — "
                    "bvps and fcf_per_share will be NaN. "
                    "Merge sharesoutstanding from Downloader.get_info_data() before calling evaluate()."
                )
                shares = pd.Series(np.nan, index=d.index)

            # valuation
            # currentprice and marketcap come from get_info_data() and must be merged
            # in by the caller before constructing FundamentalTraderAssistant.
            # Fall back to NaN series if absent so that valuation metrics are NaN
            # rather than crashing the whole method.
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

            # Ensure columns that some sectors (e.g. banks) structurally omit are
            # present before any formula references them.  Missing columns become a
            # column of NaN, so all downstream safe_div() calls produce NaN scores
            # instead of raising KeyError.  See _REQUIRED_METRIC_COLS.
            for _col in _REQUIRED_METRIC_COLS:
                if _col not in d.columns:
                    _logger.warning(
                        "[%s] column '%s' absent — metric(s) that depend on it will be NaN",
                        self.ticker, _col,
                    )
                    d[_col] = np.nan

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
            # d.get() returns the column if present, or a NaN Series — prevents
            # KeyError on tickers that don't report inventory/working_capital.
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
            # tax_rate_for_calcs and invested_capital may be absent for some tickers.
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

    def _score_metric(self, df):
        """
        Apply trader-friendly scoring rules to a DataFrame with 'metrics' and 'value' columns.

        Returns a new DataFrame — does not mutate the input.
        """
        df = df.copy()
        thresholds = {
            # Original 11
            "GrossMargin":         [0.2, 0.3, 0.4, 0.5],
            "OperatingMargin":     [0.05, 0.1, 0.15, 0.2],
            "NetProfitMargin":     [0.03, 0.07, 0.12, 0.2],
            "EBITDAMargin":        [0.1, 0.2, 0.3, 0.4],
            "ROA":                 [0.02, 0.05, 0.08, 0.12],
            "ROE":                 [0.05, 0.1, 0.15, 0.2],
            "FCFToRevenue":        [0.02, 0.05, 0.1, 0.2],
            "FCFYield":            [0.02, 0.04, 0.06, 0.1],
            "DebtToEquity":        [0.5, 1.0, 1.5, 2.0],   # inverse: lower is better
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

        # Metrics where a lower value is better: raw digitize score is inverted via 6 - score.
        _INVERSE_METRICS = frozenset(
            {"DebtToEquity", "DebtRatio", "NetDebtToEBITDA", "CapexRatio"}
        )

        def score_row(row):
            name, value = row['metrics'], row['value']
            if pd.isna(value):
                return 3
            if name in thresholds:
                score = np.digitize(value, thresholds[name]) + 1
                if name in _INVERSE_METRICS:
                    return 6 - score  # inverse: high raw value → low score
                return score
            return 3

        df['score'] = df.apply(score_row, axis=1)
        return df
    
    # def get_metric_category(self, metric):
    #     for category, metrics in self.weights.items():
    #         if metric in metrics:
    #             return category
    #     return "Uncategorized"
    
    def compute_scores(self):
        try:
            if self.metrics is None or self.metrics.empty:
                self.compute_metrics()

            # Derive scored columns dynamically from compute_metrics() output.
            # All columns except the identity variables are metric columns.
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
            # Store in metric_scores (long, per-metric) — NOT self.scores (composite).
            self.metric_scores = scored
            return scored
        except Exception as e:
            _logger.error(f"[{self.ticker}] compute_scores failed: {e}", exc_info=True)
            return pd.DataFrame()

    def raw_red_flags(self):
        try:
            # reindex instead of hard bracket select: columns absent for some sectors
            # (e.g. 'ebitda' for banks) are filled with NaN instead of raising KeyError.
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

        Returns
        -------
        pd.DataFrame
            Columns: ticker, time, sector + 14 unscored metric columns.
            Returns an empty DataFrame if an unrecoverable error occurs.
        """
        try:
            # Sort by time on a copy — never mutate self.d.
            d = self.d.copy().sort_values("time").reset_index(drop=True)

            # Optional columns: use d.get() so that missing columns produce NaN
            # rather than KeyError (which the broad except would silently swallow).
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
            # CCC = DSO + DIO − DPO; NaN if any component is NaN.
            d["CCC"] = np.where(
                pd.isna(d["DSO"]) | pd.isna(d["DIO"]) | pd.isna(d["DPO"]),
                np.nan,
                d["DSO"] + d["DIO"] - d["DPO"],
            )

            # ── Growth rates (requires time-sorted data — see sort above) ─────
            d["RevenueGrowth"]   = d["total_revenue"].pct_change()
            d["NetIncomeGrowth"] = d["net_income_common_stockholders"].pct_change()
            d["FCFGrowth"]       = d["free_cash_flow"].pct_change()

            # ── Red-flag ratios ───────────────────────────────────────────────
            # Accruals > 0 means reported income outpaces cash generation (warning).
            d["Accruals"] = self.safe_div(
                d["net_income_common_stockholders"] - d["operating_cash_flow"],
                d["total_assets"],
            )
            d["DebtGrowth"] = d["total_debt"].pct_change()
            d["Dilution"]   = _shares.pct_change()
            # capex is typically negative in yfinance; abs() gives the magnitude.
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
        # Step 1: Apply single-metric red flags
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
            Callers that need a soft result should catch EvaluationError explicitly
            and call _empty_result() themselves — this method never silently returns
            empty DataFrames on failure.

        Design note
        -----------
        The previous implementation caught all exceptions and returned _empty_result().
        That made it impossible for callers to distinguish a failure from a legitimate
        empty result, causing the LLM pipeline to receive "[]" payloads and produce
        hallucinated assessments. Raising on failure forces callers to be explicit.
        """
        try:
            # Step 1: Compute metrics
            m = self.compute_metrics()

            # Guard: compute_metrics() returns an empty DataFrame on failure.
            # Without this check the melt() below crashes with a misleading
            # KeyError (ticker/time absent) that obscures the real root cause.
            if m.empty:
                raise EvaluationError(
                    f"[{self.ticker}] compute_metrics() returned empty — "
                    "check logs for the underlying error."
                )

            ev = self.compute_valuation_metrics()

            # Step 2: Detect raw red flags (custom logic, if defined elsewhere)
            d = self.raw_red_flags()

            # Step 3: Reshape metrics for scoring and flagging.
            # Derive scored columns dynamically — keeps in sync with compute_metrics()
            # without a hardcoded list. Any column that is not an identity variable is
            # treated as a scored metric.
            _id_vars = {"ticker", "time", "sector"}
            scored_cols = [c for c in m.columns if c not in _id_vars]
            m_long = m.melt(
                id_vars=["ticker", "time"],
                value_vars=scored_cols,
                var_name="metrics",
                value_name="value"
            )

            # Step 4: Score metrics
            s = self._score_metric(m_long)

            # Step 5: Merge weights
            s = s.merge(self.weights, how="left", on="metrics")
            missing_weights = s[s["weights"].isna()]["metrics"].unique().tolist()
            if missing_weights:
                _logger.warning(
                    f"[{self.ticker}] Metrics missing weights after merge: {missing_weights}. "
                    "These metrics will be excluded from the composite score."
                )

            # Step 6: Compute composite scores via the shared static method.
            self.scores = self._compute_composite_scores(s)

            # Step 7: Detect red flags
            rf = self._metrics_red_flags(m_long)
            self.red_flags = rf[["ticker", "time", "metrics", "red_flag"]]

            # Step 8: Compute extended (unscored) metrics
            ext = self.compute_extended_metrics()

            # Step 9: Return all results
            return {
                "metrics": self.metrics,
                "eval_metrics": self.eval_metrics,
                "composite_scores": self.scores,
                "raw_red_flags": d,
                "red_flags": self.red_flags,
                "extended_metrics": ext,
            }

        except EvaluationError:
            raise  # already has context — don't wrap again
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