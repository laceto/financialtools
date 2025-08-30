from financialtools.utils import get_tickers, export_to_xlsx            
from financialtools.wrappers import DownloaderWrapper
import pandas as pd

tickers = get_tickers(
    filepath= 'financialtools/data/sector_ticker.txt',
    columns="ticker")[:1].to_list()

print(tickers)


data = DownloaderWrapper.download_data(tickers)
export_to_xlsx(df=data, path='financial_data/prova_financial_data.xlsx', sheet_name='sheet1')

# # import pandas as pd

# data = pd.read_excel('financial_data/financial_data.xlsx', sheet_name='sheet1')

# from financialtools.utils import get_tickers, export_to_xlsx
# from financialtools.config import grouped_weights
# from financialtools.wrappers import FundamentalEvaluator, export_financial_results

# tickers = get_tickers(columns='ticker').to_list()[:2]

# fundamental_eval = FundamentalEvaluator(data, grouped_weights)
# results = fundamental_eval.evaluate_multiple(tickers, parallel=True)
# export_financial_results(results, output_dir='financial_data', sheet_name='sheet1')

