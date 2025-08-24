import polars as pl
import pandas as pd
import time
from financialtools.processor import Downloader
            
            
# Instantiate the processor for a specific ticker
# processor = FinancialDataProcessor.from_ticker("TGYM.MI")

# Get merged financial data
# merged_data = processor.get_merged_data()
# print(merged_data.head())

# Export to CSV
# processor.export_to_csv("aapl_financials.csv")
# processor.export_to_xlsx("aapl_financials.xlsx", "aapl")



tickers = (
    pl.read_csv("financialtools/data/sector_ticker.txt", separator="\t")
    .select(["ticker", "sector", "name", "marginabile"])
)


def get_nested_data(ticker):
    try:
        time.sleep(1)  # Pause for one a second
        processor = FinancialDataProcessor.from_ticker(ticker)
        merged_data = processor.get_merged_data()
        return merged_data
    except Exception as e:
        print(f"Error fetching data for ticker '{ticker}': {e}")
        return None

fin_data = []
tickers = tickers["ticker"]

for ticker in tickers:
    data = get_nested_data(ticker)
    if data is not None:
        print(data)
        fin_data.append(data)

# Step 1: Concatenate all DataFrames in fin_data
combined_df = pd.concat(fin_data, ignore_index=True)

# Step 2: Export to Excel
combined_df.to_excel("financialtools/data/financial_data.xlsx", index=False)

