# utils.py placeholder

import pandas as pd
import polars as pl
import numpy as np
from financialtools.processor import FundamentalTraderAssistant
import json

def preprocess_df(df, ticker):
    """
    Preprocesses the input DataFrame by:
    - Filtering rows for the specified ticker
    - Extracting the year from the 'time' column
    - Reordering columns to place 'time' last

    Parameters:
        df (pd.DataFrame): Original DataFrame
        ticker (str): Ticker symbol to filter by

    Returns:
        pd.DataFrame: Preprocessed DataFrame
    """
    try:
        return (
            pl.from_pandas(df)
            .filter(pl.col("ticker") == ticker)
            .with_columns(pl.col("time").dt.year().alias("time"))
            .select([col for col in df.columns if col != "time"] + ["time"])
            .to_pandas()
        )
    except Exception as e:
        print(f"Error preprocessing data for ticker {ticker}: {e}")
        return pd.DataFrame()  # Return empty DataFrame on failure

def get_fundamental_output(df, ticker, weights):
    """
    Evaluates fundamental metrics for a given ticker using the FundamentalTraderAssistant.

    Parameters:
        df (pd.DataFrame): Original DataFrame
        ticker (str): Ticker symbol to evaluate
        weights (dict): Grouped weights for evaluation

    Returns:
        dict: Dictionary containing evaluation results
    """
    try:
        processed_df = preprocess_df(df, ticker)
        if processed_df.empty:
            raise ValueError("Processed DataFrame is empty.")
        assistant = FundamentalTraderAssistant(data=processed_df, weights=weights)
        return assistant.evaluate()
    except Exception as e:
        print(f"Error evaluating ticker {ticker}: {e}")
        return {
            'metrics': pd.DataFrame(),
            'composite_scores': pd.DataFrame(),
            'red_flags': pd.DataFrame(),
            'raw_red_flags': pd.DataFrame()
        }

def merge_results(results, key):
    """
    Merges a specific key from multiple result dictionaries into a single DataFrame.

    Parameters:
        results (list): List of result dictionaries
        key (str): Key to extract and merge

    Returns:
        pd.DataFrame: Concatenated DataFrame for the specified key
    """
    try:
        return pd.concat([result.get(key) for result in results], ignore_index=True)
    except Exception as e:
        print(f"Error merging results for key '{key}': {e}")
        return pd.DataFrame()

def get_ticker_list():

    df = pd.read_excel('financialtools/data/metrics.xlsx')
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

    return tickers

# print(get_ticker_list())

def get_fin_data(ticker):
    # print(ticker)
    metrics = (pl.from_pandas(pd.read_excel('financialtools/data/metrics.xlsx'))
        .filter(pl.col("ticker") == ticker)
        .to_pandas())
    metrics = metrics.round(2)
    metrics = metrics.to_dict()
    # metrics = metrics.to_json(orient="records")
    metrics = json.dumps(metrics)


    composite_scores = (pl.from_pandas(pd.read_excel('financialtools/data/composite_scores.xlsx'))
        .filter(pl.col("ticker") == ticker)
        .to_pandas())
    composite_scores = composite_scores.to_dict()
    composite_scores = json.dumps(composite_scores)


    red_flags = pl.concat([
        (pl.from_pandas(pd.read_excel('financialtools/data/red_flags.xlsx'))
            .filter(pl.col("ticker") == ticker)),
        (pl.from_pandas(pd.read_excel('financialtools/data/raw_red_flags.xlsx'))
            .filter(pl.col("ticker") == ticker))]
    ).to_pandas()
    red_flags = red_flags.to_dict()
    red_flags = json.dumps(red_flags)

    # fin_data = f"The ticker is:\n{ticker}.\nMetrics:\n{metrics}\n.Composite scores:\n{composite_scores}\nRed flags:\n{red_flags}"

    return metrics, composite_scores, red_flags