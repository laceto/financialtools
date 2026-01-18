import yfinance as yf
import os
import pandas as pd
from time import sleep
from typing import Dict, Any, List
import numpy as np

class RateLimiter:
    def __init__(self, per_minute=60, per_hour=360, per_day=8000):
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.per_day = per_day
        self.calls = []
    
    def acquire(self):
        import time
        now = time.time()
        self.calls = [t for t in self.calls if now - t < 86400]
        if len(self.calls) >= self.per_day:
            sleep(3600)
        self.calls.append(now)
        sleep(1.0 / self.per_minute)  # basic throttle


class Downloader:
    def __init__(self, ticker):
        self.ticker = ticker
        self._balance_sheet = None
        self._income_stmt = None
        self._cashflow = None
        self._info = None

    # @classmethod
    # def from_ticker(cls, ticker):
    #     t = yf.Ticker(ticker)
    #     d = cls(ticker)
    #     d._balance_sheet = t.balance_sheet
    #     d._income_stmt = t.income_stmt
    #     d._cashflow = t.cashflow
    #     d._info = t.info
    #     return d
    
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
            print(f"Failed to download {ticker}: {e}")
            return cls(ticker)
            
    # @staticmethod
    # def __format_fin_data(ticker: str, data_type: str, df: pd.DataFrame) -> pd.DataFrame:
    #     if df is None or df.empty:
    #         return pd.DataFrame()
    #     df = df.reset_index()
    #     df["ticker"] = ticker
    #     df["docs"] = data_type
    #     return df


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
        if self._info.empty:
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
                    except:
                        pass  # silently skip file write errors

                # Optional JSON save block
                # try:
                #     if d._info:
                #         info_path = os.path.join(out_dir, f"{t}_info.json")
                #         pd.Series(d._info).to_json(info_path, indent=2)
                # except:
                #     pass

                print(f"Saved {t} data to {out_dir}")
                yield d

            except:
                pass  # silently skip ticker-level errors




class FundamentalTraderAssistant:
    """
    An assistant class for analyzing fundamental financial metrics and identifying red flags
    in company financial data.
    """

    def __init__(self, data: pd.DataFrame, weights: pd.DataFrame):
        self.d = data
        self.metrics = {}
        self.eval_metrics = {}
        self.scores = {}
        self.weights = weights
        self.ticker = data['ticker'].unique()[0]
        self.sector = weights['sector'].unique()[0]
        # self.weights = get_sector_weights(self.sector)


    def safe_div(self, num, den):
        try:
            return np.where((den != 0) & (den.notna()) & (num.notna()), num / den, np.nan)
        except Exception as e:
            print(f"Error in safe_div: {e}")
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
            print(f"Error in compute_metrics: {e}")
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
            print(f"Error in compute_metrics: {e}")
            return pd.DataFrame()

    def score_metric(self, df):
        """
        Apply trader-friendly scoring rules to a DataFrame with 'metrics' and 'value' columns.
        """
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

            df = self.metrics.melt(id_vars=["ticker", "time"], var_name="metrics", value_name="value")
            scored = self.score_metric(df)
            # Add category column
            # scored["category"] = scored["metrics"].apply(self.get_metric_category)
            scored['sector'] = self.sector
            self.scores = scored
            return scored
        except Exception as e:
            print(f"Error in compute_scores: {e}")
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
            print(f"Error in raw_red_flags: {e}")
            return pd.DataFrame()

    def metrics_red_flags(self, df):
        """Add red flag names to a long-format DataFrame with 'metrics' and 'value' columns."""

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
        
    def evaluate(self):
        """
        Evaluate financial metrics, compute scores, detect red flags, and return a summary.

        Returns:
        - dict: {
            "metrics": pd.DataFrame,
            "composite_scores": pd.DataFrame,
            "raw_red_flags": pd.DataFrame,
            "red_flags": pd.DataFrame
        }
        """
        try:
            # Step 1: Compute metrics
            m = self.compute_metrics()
            ev = self.compute_valuation_metrics()

            # Step 2: Detect raw red flags (custom logic, if defined elsewhere)
            d = self.raw_red_flags()

            # Step 3: Reshape metrics for scoring and flagging
            m_long = m.melt(
                id_vars=["ticker", "time"],
                value_vars=m.loc[:, "GrossMargin":"CurrentRatio"].columns,
                var_name="metrics",
                value_name="value"
            )

            # Step 4: Score metrics
            s = self.score_metric(m_long)

            # Step 5: Merge weights
            # weights = pd.DataFrame(list(self.weights.items()), columns=["metrics", "Weight"])

            # weights = self.weightscompute_composite_scores
            s = s.merge(self.weights, how="left", on="metrics")

            # Step 6: Compute composite scores
            def compute_composite_scores(df: pd.DataFrame) -> pd.DataFrame:
                df["weighted_score"] = df["score"] * df["weights"]
                composite = (
                    df.groupby(["ticker", "time", "sector"], as_index=False)
                    .agg(
                        total_weighted_score=("weighted_score", "sum"),
                        total_weight=("weights", "sum")
                    )
                )
                composite["composite_score"] = composite["total_weighted_score"] / composite["total_weight"]
                return composite[["sector","ticker", "time", "composite_score"]]

            self.scores = compute_composite_scores(s)

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
            print(f"Error in evaluate: {e}")
            return {
                "metrics": pd.DataFrame(),
                "composite_scores": pd.DataFrame(),
                "raw_red_flags": pd.DataFrame(),
                "red_flags": pd.DataFrame(),
            }