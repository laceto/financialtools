import pandas as pd
import numpy as np

class FundamentalTraderAssistant:
    """
    An assistant class for analyzing fundamental financial metrics and identifying red flags
    in company financial data.
    """

    def __init__(self, data: pd.DataFrame, weights: dict):
        self.d = data
        self.metrics = {}
        self.scores = {}
        # Store grouped weights
        self.weights = weights

        # Flatten weights for scoring
        self.w = {
            metric: weight
            for group in weights.values()
            for metric, weight in group.items()
        }

    def safe_div(self, num, den):
        try:
            return np.where((den != 0) & (den.notna()) & (num.notna()), num / den, np.nan)
        except Exception as e:
            print(f"Error in safe_div: {e}")
            return pd.Series([np.nan] * len(num))

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
            d["FCFYield"] = self.safe_div(d["free_cash_flow"], d["total_capitalization"])
            d["FCFtoDebt"] = self.safe_div(d["free_cash_flow"], d["total_debt"])

            # Leverage & Liquidity
            d["DebtToEquity"] = self.safe_div(d["total_debt"], d["common_stock_equity"])
            d["CurrentRatio"] = self.safe_div(d["working_capital"], d["total_liabilities_net_minority_interest"])

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
    
    def get_metric_category(self, metric):
        for category, metrics in self.weights.items():
            if metric in metrics:
                return category
        return "Uncategorized"
    
    def compute_scores(self):
        try:
            if self.metrics is None or self.metrics.empty:
                self.compute_metrics()

            df = self.metrics.melt(id_vars=["ticker", "time"], var_name="metrics", value_name="value")
            scored = self.score_metric(df)
            # Add category column
            scored["category"] = scored["metrics"].apply(self.get_metric_category)

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
            weights = pd.DataFrame(list(self.w.items()), columns=["metrics", "Weight"])
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


df = pd.read_excel('df.xlsx', sheet_name='TGYM.MI')
# print(df)

# weights = {
#     "GrossMargin": 8, 
#     "OperatingMargin": 12, 
#     "NetProfitMargin": 8, 
#     "EBITDAMargin": 10,
#     "ROA": 10, 
#     "ROE": 12,
#     "FCFToRevenue": 10, 
#     "FCFYield": 10,
#     "FCFToDebt": 10,
#     "DebtToEquity": 12, 
#     "CurrentRatio": 8,
# }

grouped_weights = {
    "Profitability & Margins": {
        "GrossMargin": 8,
        "OperatingMargin": 12,
        "NetProfitMargin": 8,
        "EBITDAMargin": 10
    },
    "Returns": {
        "ROA": 10,
        "ROE": 12
    },
    "Leverage & Solvency": {
        "DebtToEquity": 12,
        "DebtToAssets": 10
    },
    "Liquidity": {
        "CurrentRatio": 8
    },
    "Cash Flow Strength": {
        "FCFToRevenue": 10,
        "FCFYield": 10
    }
}

assistant = FundamentalTraderAssistant(data=df, weights=grouped_weights)

eval = assistant.evaluate()
print(eval.get('red_flags'))

# print(eval)
# flags_df = assistant.raw_red_flags()