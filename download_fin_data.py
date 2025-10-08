import json
import pandas as pd

# Load JSON as dict
with open('./financialtools/data/company_tickers.json') as f:
    data = json.load(f)

# Convert to long format
tickers = pd.DataFrame.from_dict(data, orient='index').reset_index()
tickers.drop(columns='index', inplace=True)
tickers = tickers['ticker'].to_list()

from financialtools.processor import Downloader  # Assume the updated Downloader class is in downloader.py
import os

# List of tickers, including an invalid ticker (DVLT)
# tickers = tickers[:50]

# Set custom cache location
cache_path = "./cache"
os.makedirs(cache_path, exist_ok=True)  # Create cache directory if it doesn't exist

# Fetch data in batches of 4 with 1-second sleep, using custom cache
downloaders = Downloader.from_ticker(tickers, batch_size=5, sleep_time=2.0, max_workers=5, 
                                    verbose=False, cache_location=cache_path)

financial_data = Downloader.combine_merged_data(downloaders)
info_data = Downloader.combine_info_data(downloaders)

from financialtools.utils import export_to_xlsx
export_to_xlsx(df=financial_data, path='financial_data/sec_financial_data.xlsx', sheet_name='sheet1')
export_to_xlsx(df=financial_data, path='financial_data/sec_info_data.xlsx', sheet_name='sheet1')



