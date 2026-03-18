import yfinance as yf
import os
import pandas as pd
from time import sleep
from typing import Dict, Any, List
from financialtools.exceptions import EvaluationError
import numpy as np
import logging as _logging

# Module-level logger — defined here (before all class bodies) so every method
# can reference _logger at call time without an ordering hazard.
_logger = _logging.getLogger(__name__)


class RateLimiter:
    """
    Token-bucket style rate limiter with sliding-window guards.

    Thread-safe: all state mutations are protected by a threading.Lock.
    acquire() is safe to call from multiple threads sharing one instance.

    Limits:
      per_minute  — max calls within any 60-second window
      per_hour    — max calls within any 3600-second window
      per_day     — max calls within any 86400-second window

    acquire() sleeps until all three windows have a free slot, then records
    the call timestamp.
    """

    def __init__(self, per_minute=60, per_hour=360, per_day=8000):
        import threading
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.per_day = per_day
        self.calls = []
        self._lock = threading.Lock()

    def acquire(self):
        """
        Block until a call is permissible under all three rate limits.

        Uses sliding-window checks. Refreshes timestamps after each sleep so
        stale-now values do not cause limit overruns. All state access is
        protected by self._lock.
        """
        import time
        with self._lock:
            while True:
                now = time.time()
                # Prune calls older than 24 h to bound list growth.
                self.calls = [t for t in self.calls if now - t < 86400]

                calls_last_minute = [t for t in self.calls if now - t < 60]
                calls_last_hour   = [t for t in self.calls if now - t < 3600]

                wait = 0.0
                if len(calls_last_minute) >= self.per_minute and calls_last_minute:
                    wait = max(wait, 60 - (now - calls_last_minute[0]))
                if len(calls_last_hour) >= self.per_hour and calls_last_hour:
                    wait = max(wait, 3600 - (now - calls_last_hour[0]))
                if len(self.calls) >= self.per_day and self.calls:
                    wait = max(wait, 86400 - (now - self.calls[0]))

                if wait <= 0.0:
                    break  # all limits satisfied — proceed
                sleep(max(0.0, wait))
                # Re-enter loop to recompute with fresh timestamps after sleep.

            self.calls.append(time.time())


class Downloader:
    def __init__(self, ticker):
        self.ticker = ticker
        self._balance_sheet = None
        self._income_stmt = None
        self._cashflow = None
        self._info = None

    @classmethod
    def from_ticker(cls, ticker):
        """Download and reshape all financial data for one ticker."""
        import yfinance as yf

        try:
            t = yf.Ticker(ticker)
            d = cls(ticker)

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
            return cls(ticker)
            
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
    
    def get_merged_data(self) -> pd.DataFrame:
        """
        Merge balance sheet, income statement, and cash flow data for a single ticker.
        """
        try:
            dfs = [self._balance_sheet, self._cashflow, self._income_stmt]
            # Ensure all are non-empty and have required columns
            dfs = [df for df in dfs if isinstance(df, pd.DataFrame) and not df.empty]
            if len(dfs) < 2:
                return pd.DataFrame()

            # Perform merge on ['ticker', 'time']
            merged = dfs[0]
            for df in dfs[1:]:
                merged = merged.merge(df, how="left", on=["ticker", "time"])

            if merged.empty:
                return pd.DataFrame()

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
    def stream_download(cls, tickers, limiter, out_dir="financial_data"):
        """Stream tickers one by one, save each to Parquet/JSON as soon as ready."""
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
_EMPTY_RESULT_KEYS = ("metrics", "eval_metrics", "composite_scores", "raw_red_flags", "red_flags")


def _empty_result() -> dict:
    """Return a fresh dict of empty DataFrames with the canonical evaluate() shape."""
    return {k: pd.DataFrame() for k in _EMPTY_RESULT_KEYS}


# Reference list of metric column names produced by compute_metrics().
# Used as documentation and for score_metric() threshold key alignment.
# evaluate() and compute_scores() derive value_vars dynamically from compute_metrics()
# output columns so that adding a new metric to compute_metrics() is automatically scored.
SCORED_METRICS: list = [
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
]


class FundamentalTraderAssistant:
    """
    An assistant class for analyzing fundamental financial metrics and identifying red flags
    in company financial data.
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
            # valuation
            d['bvps'] = d["common_stock_equity"] / d['sharesoutstanding']
            d['fcf_per_share'] = self.safe_div(d["free_cash_flow"], d["sharesoutstanding"])
            d['eps'] = d['diluted_eps']

            d["P/E"] = self.safe_div(d["currentprice"], d["eps"])
            d["P/B"] = self.safe_div(d["currentprice"], d["bvps"])
            d["P/FCF"] = self.safe_div(d["currentprice"], d["fcf_per_share"])
            d["EarningsYield"] = self.safe_div(d["eps"], d["currentprice"])
            d["FCFYield"] = self.safe_div(d["free_cash_flow"], d["marketcap"])

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

            # Profitability Margins
            d["GrossMargin"] = self.safe_div(d["gross_profit"], d["total_revenue"])
            d["OperatingMargin"] = self.safe_div(d["operating_income"], d["total_revenue"])
            d["NetProfitMargin"] = self.safe_div(d["net_income_common_stockholders"], d["total_revenue"])
            d["EBITDAMargin"] = self.safe_div(d["ebitda"], d["total_revenue"])

            # Returns
            d["ROA"] = self.safe_div(d["net_income_common_stockholders"], d["total_assets"])
            d["ROE"] = self.safe_div(d["net_income_common_stockholders"], d["common_stock_equity"])

            # Cash Flow Metrics
            d["FCFToRevenue"] = self.safe_div(d["free_cash_flow"], d["total_revenue"])
            d["FCFYield"] = self.safe_div(d["free_cash_flow"], d["marketcap"])
            d["FCFtoDebt"] = self.safe_div(d["free_cash_flow"], d["total_debt"])

            # Leverage & Liquidity
            d["DebtToEquity"] = self.safe_div(d["total_debt"], d["common_stock_equity"])
            d["CurrentRatio"] = self.safe_div(d["current_assets"], d["current_liabilities"])

            metric_cols = ["GrossMargin", "OperatingMargin", "NetProfitMargin", "EBITDAMargin",
                           "ROA", "ROE", "FCFToRevenue", "FCFYield", "FCFtoDebt",
                           "DebtToEquity", "CurrentRatio"]

            d = d[["ticker", "time"] + metric_cols]
            d['sector'] = self.sector
            self.metrics = d
            return d
        except Exception as e:
            _logger.error(f"[{self.ticker}] compute_metrics failed: {e}", exc_info=True)
            return pd.DataFrame()

    def score_metric(self, df):
        """
        Apply trader-friendly scoring rules to a DataFrame with 'metrics' and 'value' columns.

        Returns a new DataFrame — does not mutate the input.
        """
        df = df.copy()
        thresholds = {
            "GrossMargin": [0.2, 0.3, 0.4, 0.5],
            "OperatingMargin": [0.05, 0.1, 0.15, 0.2],
            "NetProfitMargin": [0.03, 0.07, 0.12, 0.2],
            "EBITDAMargin": [0.1, 0.2, 0.3, 0.4],
            "ROA": [0.02, 0.05, 0.08, 0.12],
            "ROE": [0.05, 0.1, 0.15, 0.2],
            "FCFToRevenue": [0.02, 0.05, 0.1, 0.2],
            "FCFYield": [0.02, 0.04, 0.06, 0.1],
            "DebtToEquity": [0.5, 1.0, 1.5, 2.0],  # inverse scoring
            "CurrentRatio": [1.0, 1.2, 1.5, 2.0],
            "FCFtoDebt": [0.05, 0.1, 0.2, 0.3],
        }

        def score_row(row):
            name, value = row['metrics'], row['value']
            if pd.isna(value):
                return 3
            if name in thresholds:
                score = np.digitize(value, thresholds[name]) + 1
                if name == "DebtToEquity":
                    return 6 - score  # inverse scoring
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
            scored = self.score_metric(df)
            scored['sector'] = self.sector
            # Store in metric_scores (long, per-metric) — NOT self.scores (composite).
            self.metric_scores = scored
            return scored
        except Exception as e:
            _logger.error(f"[{self.ticker}] compute_scores failed: {e}", exc_info=True)
            return pd.DataFrame()

    def raw_red_flags(self):
        try:
            d = self.d[["ticker", "time", "free_cash_flow", "operating_cash_flow", "ebitda"]].copy()

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

    def metrics_red_flags(self, df):
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
        Invariant: weights come from sector_metric_weights via the self.weights merge in evaluate().
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

        Returns:
        - dict with keys matching _EMPTY_RESULT_KEYS:
            "metrics": pd.DataFrame,
            "eval_metrics": pd.DataFrame,
            "composite_scores": pd.DataFrame,
            "raw_red_flags": pd.DataFrame,
            "red_flags": pd.DataFrame
        """
        try:
            # Step 1: Compute metrics
            m = self.compute_metrics()
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
            s = self.score_metric(m_long)

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
            rf = self.metrics_red_flags(m_long)
            self.red_flags = rf[["ticker", "time", "metrics", "red_flag"]]

            # Step 8: Return all results
            return {
                "metrics": self.metrics,
                "eval_metrics": self.eval_metrics,
                "composite_scores": self.scores,
                "raw_red_flags": d,
                "red_flags": self.red_flags,
            }

        except Exception as e:
            _logger.error(f"[{getattr(self, 'ticker', '?')}] evaluate() failed: {e}", exc_info=True)
            return _empty_result()