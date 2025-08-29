# from financialtools.utils import get_tickers, export_to_xlsx            
# from financialtools.wrappers import DownloaderWrapper
# import pandas as pd

# tickers = get_tickers(
#     filepath= 'financialtools/data/sector_ticker.txt',
#     columns="ticker")[:2].to_list()


# data = DownloaderWrapper.download_data(tickers)
# export_to_xlsx(df=data, path='financial_data/financial_data.xlsx', sheet_name='sheet1')

# # import pandas as pd

# data = pd.read_excel('financial_data/financial_data.xlsx', sheet_name='sheet1')

# from financialtools.utils import get_tickers, export_to_xlsx
# from financialtools.config import grouped_weights
# from financialtools.wrappers import FundamentalEvaluator, export_financial_results

# tickers = get_tickers(columns='ticker').to_list()[:2]

# fundamental_eval = FundamentalEvaluator(data, grouped_weights)
# results = fundamental_eval.evaluate_multiple(tickers, parallel=True)
# export_financial_results(results, output_dir='financial_data', sheet_name='sheet1')

def read_financial_results(ticker=None, time=None, input_dir="financial_data", sheet_name="sheet1"):
    """
    Reads specific Excel files and returns selected DataFrames.
    Optionally filters each DataFrame by ticker and/or year.

    Returns:
        metrics, composite_scores, red_flags (DataFrames)
    """
    import os
    import pandas as pd

    def read_and_filter(filename):
        path = os.path.join(input_dir, f"{filename}.xlsx")
        try:
            df = pd.read_excel(path, sheet_name=sheet_name)

            # Apply filters if columns exist
            if ticker is not None and "ticker" in df.columns:
                df = df[df["ticker"] == ticker]
            if time is not None and "time" in df.columns:
                df = df[df["time"] == time]

            return df
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            return pd.DataFrame()

    metrics = read_and_filter("metrics")
    eval_metrics = read_and_filter("eval_metrics")
    composite_scores = read_and_filter("composite_scores")
    red_flags = read_and_filter("red_flags")
    raw_red_flags = read_and_filter("red_flags")

    red_flags = pd.concat([red_flags, raw_red_flags], axis=0, ignore_index=True)

    return metrics, eval_metrics, composite_scores, red_flags



metrics, eval_metrics, composite_scores, red_flags = read_financial_results(
    ticker='AVIO.MI',
    time=2024,
    input_dir='financial_data', 
    sheet_name='sheet1')

print(red_flags)