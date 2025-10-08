import json
import pandas as pd

# Load JSON as dict
with open('./financialtools/data/company_tickers.json') as f:
    data = json.load(f)

# Convert to long format
tickers = pd.DataFrame.from_dict(data, orient='index').reset_index()
tickers.drop(columns='index', inplace=True)
tickers = tickers['ticker'].to_list()
tickers = tickers[:5]
from financialtools.processor import Downloader, RateLimiter  # Assume the updated Downloader class is in downloader.py

limiter = RateLimiter(per_minute=60, per_hour=360, per_day=8000)

for dl in Downloader.stream_download(tickers, limiter):
    print(f"{dl.ticker} ready → {len(dl._balance_sheet)} rows")



