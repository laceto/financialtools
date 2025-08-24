
from financialtools.utils import *


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


import polars as pl
df = pd.read_excel('financialtools/data/financial_data.xlsx')
df.columns = df.columns.str.lower().str.replace(" ", "_")



# Get unique tickers
try:
    tickers = (
        pl.from_pandas(df)
        .select("ticker")
        .unique()
        .get_column("ticker")
        .to_list()
    )
except Exception as e:
    print(f"Error extracting tickers: {e}")
    tickers = []

# Evaluate and collect results
results = [
    get_fundamental_output(df, ticker, grouped_weights)
    for ticker in tickers
]

# Merge outputs
metrics = merge_results(results, "metrics")
composite_scores = merge_results(results, "composite_scores")
red_flags = merge_results(results, "red_flags")
raw_red_flags = merge_results(results, "raw_red_flags")


metrics.to_excel("financialtools/data/metrics.xlsx", index=False)
raw_red_flags.to_excel("financialtools/data/raw_red_flags.xlsx", index=False)
red_flags.to_excel("financialtools/data/red_flags.xlsx", index=False)
composite_scores.to_excel("financialtools/data/composite_scores.xlsx", index=False)

