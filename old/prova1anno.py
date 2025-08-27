from financialtools.utils import *

def get_last_fin_data(ticker, year):
    # print(ticker)
    metrics = (pl.from_pandas(pd.read_excel('financialtools/data/metrics.xlsx'))
        .filter(pl.col("ticker") == ticker)
        .filter(pl.col("time") == year)
        .to_pandas())
    metrics = metrics.round(2)
    metrics = metrics.to_dict()
    metrics = json.dumps(metrics)


    composite_scores = (pl.from_pandas(pd.read_excel('financialtools/data/composite_scores.xlsx'))
        .filter(pl.col("ticker") == ticker)
        .to_pandas())
    composite_scores = composite_scores.to_dict()
    composite_scores = json.dumps(composite_scores)


    red_flags = pl.concat([
        (pl.from_pandas(pd.read_excel('financialtools/data/red_flags.xlsx'))
            .filter(pl.col("ticker") == ticker)
            .filter(pl.col("time") == year)
            ),
        (pl.from_pandas(pd.read_excel('financialtools/data/raw_red_flags.xlsx'))
            .filter(pl.col("ticker") == ticker)
            .filter(pl.col("time") == year)
            )]
    ).to_pandas()
    red_flags = red_flags.to_dict()
    red_flags = json.dumps(red_flags)

    return metrics, composite_scores, red_flags

ticker = 'FCT.MI'
metrics, composite_scores, red_flags = get_last_fin_data(ticker, 2024)

print(red_flags)



