
from financialtools.utils import get_tickers, export_to_xlsx            
from financialtools.wrappers import DownloaderWrapper

tickers = get_tickers(
    filepath= 'financialtools/data/sector_ticker.txt',
    columns="ticker")[:2].to_list()


data = DownloaderWrapper.download_data(tickers)

print(data)

export_to_xlsx(df=data, path='financial_data/financial_data.xlsx', sheet_name='sheet1')



