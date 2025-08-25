import yfinance as yf

ticker = 'PRY.MI'
obj = yf.Ticker(ticker)

print(obj.analyst_price_targets)

print(obj.earnings_dates)

print(obj.earnings_history)

print(obj.earnings_estimate)

print(obj.news)