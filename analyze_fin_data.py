import pandas as pd

data = pd.read_excel('financial_data/financial_data.xlsx', sheet_name='sheet1')

from financialtools.utils import get_tickers, export_to_xlsx
from financialtools.config import grouped_weights
from financialtools.wrappers import FundamentalEvaluator, export_financial_results

tickers = get_tickers(columns='ticker').to_list()[:2]

fundamental_eval = FundamentalEvaluator(data, grouped_weights)
results = fundamental_eval.evaluate_multiple(tickers, parallel=True)
export_financial_results(results, output_dir='financial_data', sheet_name='sheet1')

# print(data)
# print(tickers)

# from financialtools.processor import FundamentalTraderAssistant

# assistant = FundamentalTraderAssistant(data, grouped_weights)
# metrics = assistant.compute_metrics()

# print(data['current_assets'])