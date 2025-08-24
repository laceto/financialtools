# utils.py placeholder

import pandas as pd
import polars as pl
import numpy as np
from financialtools.processor import FundamentalTraderAssistant

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
