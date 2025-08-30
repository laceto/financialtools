import yfinance as yf
import json
import pandas as pd
import numpy as np

import polars as pl
from typing import List, Union, Optional

from financialtools.utils import get_sector_for_ticker, get_sector_weights

class Downloader:
    def __init__(self, ticker, balance_sheet, income_stmt, cashflow, info):
        self.ticker = ticker
        self._balance_sheet = balance_sheet
        self._income_stmt = income_stmt
        self._cashflow = cashflow
        self._info = info

    @classmethod
    def from_ticker(cls, ticker):
        try:
            bs = cls.__reshape_fin_data(cls.get_balance_sheet(ticker))
            inc = cls.__reshape_fin_data(cls.get_income_stmt(ticker))
            cf = cls.__reshape_fin_data(cls.get_cashflow(ticker))
            # info = cls.get_info(ticker)
            # info = cls.get_info(ticker)
            info = cls.__filter_info(cls.get_info(ticker))
            return cls(ticker, bs, inc, cf, info)
        except Exception as e:
            print(f"Failed to create FinancialDataProcessor for {ticker}: {e}")
            return cls(ticker, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    def get_merged_data(self):
        """Public method to get merged financial data."""
        try:
            df_merged = self._balance_sheet.merge(self._cashflow, how="left", on=["ticker", "time"])
            df_merged = df_merged.merge(self._income_stmt, how="left", on=["ticker", "time"])
            return df_merged.merge(self._info, how="left", on=["ticker"])
            # return pd.concat([, self._income_stmt, self._cashflow], ignore_index=True)
        except Exception as e:
            print(f"Error merging data: {e}")
            return pd.DataFrame()


    @staticmethod        
    def __filter_info(df):

        df = df[df["key"].str.contains("marketCap|sharesOutstanding|PE|regularMarketPrice|currentPrice|priceToBook", case=True, na=False)]
        df = df.pivot(
            index=["ticker"],
            columns='key',
            values='value'
        ).reset_index()
        
        return df
        
    @staticmethod
    def __reshape_fin_data(df):
        """Private method to reshape financial data."""
        try:
            pivot_vars = ["index", "ticker", "docs"]
            value_vars = [c for c in df.columns if c not in pivot_vars]

            df = df.melt(
                id_vars=pivot_vars,
                value_vars=value_vars,
                var_name="time",
                value_name="value"
            )

            df = df.pivot_table(
                index=["ticker", "docs", "time"],
                columns="index",
                values="value"
            ).reset_index()

            return df
        except Exception as e:
            print(f"Error reshaping financial data: {e}")
            return pd.DataFrame()

    @staticmethod
    def __filter_col_by(df, col, by):
        """Private method to filter a column by prefix."""
        try:
            return df[df[col].str.startswith(tuple(by))]
        except Exception as e:
            print(f"Error filtering column '{col}': {e}")
            return pd.DataFrame()
        


    # Placeholder methods for data retrieval
    @staticmethod
    def get_balance_sheet(sym):
        """Fetches and formats the balance sheet for a given ticker."""
        try:
            bs = yf.Ticker(sym).balance_sheet
            if bs is None or bs.empty:
                return pd.DataFrame()
            bs = bs.reset_index()
            bs['ticker'] = sym
            bs['docs'] = 'balance_sheet'
            return bs
        except Exception as e:
            print(f"Error retrieving balance sheet for {sym}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_income_stmt(sym):
        """Fetches and formats the income statement for a given ticker."""
        try:
            inc = yf.Ticker(sym).income_stmt
            if inc is None or inc.empty:
                return pd.DataFrame()
            inc = inc.reset_index()
            inc['ticker'] = sym
            inc['docs'] = 'income_stmt'
            return inc
        except Exception as e:
            print(f"Error retrieving income statement for {sym}: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_cashflow(sym):
        """Fetches and formats the cash flow statement for a given ticker."""
        try:
            cf = yf.Ticker(sym).cash_flow
            if cf is None or cf.empty:
                return pd.DataFrame()
            cf = cf.reset_index()
            cf['ticker'] = sym
            cf['docs'] = 'cash_flow'
            return cf
        except Exception as e:
            print(f"Error retrieving cash flow for {sym}: {e}")
            return pd.DataFrame()
        
    @staticmethod
    def get_info(sym):
        """
        Retrieve stock.info safely. Always returns a dict with:
        - 'ticker': the symbol
        - 'docs': the info dictionary (or {} if empty)
        - 'error': only if an exception occurred
        """

        try:
            stock = yf.Ticker(sym)
            info = stock.info
            if info and isinstance(info, dict):
                info = pd.DataFrame(list(info.items()), columns=["key", "value"])
                info.insert(0, "ticker", sym)
                # info.insert(1, "docs", 'info')

        except Exception as e:
            info["error"] = str(e)
        return info
        




class FundamentalTraderAssistant:
    """
    An assistant class for analyzing fundamental financial metrics and identifying red flags
    in company financial data.
    """

    def __init__(self, data: pd.DataFrame, weights: dict):
        self.d = data
        self.metrics = {}
        self.eval_metrics = {}
        self.scores = {}
        # self.weights = weights
        self.ticker = data['ticker'].unique()[0]
        self.sector = get_sector_for_ticker(self.ticker)
        self.weights = get_sector_weights(self.sector)


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
            # weights = pd.DataFrame(list(self.w.items()), columns=["metrics", "Weight"])

            

            weights = self.weights
            s = s.merge(weights, how="left", on="metrics")

            # Step 6: Compute composite scores
            def compute_composite_scores(df: pd.DataFrame) -> pd.DataFrame:
                df["weighted_score"] = df["score"] * df["Weight"]
                composite = (
                    df.groupby(["ticker", "time"], as_index=False)
                    .agg(
                        total_weighted_score=("weighted_score", "sum"),
                        total_weight=("Weight", "sum")
                    )
                )
                composite["composite_score"] = composite["total_weighted_score"] / composite["total_weight"]
                return composite[["ticker", "time", "composite_score"]]

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