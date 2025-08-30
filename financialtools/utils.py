# utils.py placeholder

import pandas as pd
import polars as pl
import numpy as np
# from financialtools.processor import FundamentalTraderAssistant
from financialtools.config import sector_metric_weights
import json

import polars as pl
from typing import List, Union, Optional

def export_to_csv(df, path):
        """Public method to export merged data to CSV."""
        try:
            df.to_csv(path, index=False)
            print(f"Data exported to {path}")
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            
def export_to_xlsx(df, path, sheet_name):
        """Public method to export merged data to CSV."""
        try:
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Data exported to {path}")
        except Exception as e:
            print(f"Error exporting to CSV: {e}")

def get_tickers(
    filepath: str = "financialtools/data/sector_ticker.txt", 
    columns: Union[List[str], str, None] = None,
    pattern: Optional[str] = None
):
    """
    Load tickers from file. Optionally select specific columns.
    - If only one column is selected, return as a Series instead of a DataFrame.
    - If pattern is provided, filters rows where `ticker` contains the pattern.
    """
    # Base DataFrame
    df = (
        pl.read_csv(filepath, separator="\t")
        .select(["ticker", "sector", "name", "marginabile"])
    )
    
    # Apply pattern filter if given
    if pattern is not None:
        df = df.filter(df["ticker"].str.contains(pattern, literal=False, strict=False))
    
    # Handle column selection
    if columns is None:
        return df
    
    if isinstance(columns, str):  # single column as string
        return df[columns]
    
    if isinstance(columns, list):  # multiple columns
        if len(columns) == 1:  # only one column
            return df[columns[0]]
        return df.select(columns)

    raise ValueError("`columns` must be None, str, or list of str")

# Example usage:
# tickers_all = get_tickers()  
# tickers_only = get_tickers(columns="ticker")  
# tickers_subset = get_tickers(columns=["ticker", "sector"])  
# tickers_filtered = get_tickers(pattern="MI", columns="ticker")  # only tickers containing "MI"



def dataframe_to_json(df):
    """
    Converts a pandas DataFrame to a JSON-formatted string.

    Parameters:
        df (pd.DataFrame): The DataFrame to convert.

    Returns:
        str: JSON-formatted string.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a pandas DataFrame.")

    df_dict = df.to_dict(orient='records')
    # df_dict = df.to_dict(orient=orient)
    json_str = json.dumps(df_dict)

    return json_str


def get_sector_weights(sector: str) -> dict:
    """
    Loads sector weights from an Excel file and returns them as a dictionary
    for the specified sector.

    Parameters:
    - sector (str): The sector to filter by.

    Returns:
    - df: Dataframe weights.
    """
    df = (
        pd.read_excel('financialtools/data/weights.xlsx')
        .melt(id_vars=["sector"], var_name="metrics", value_name="Weight")
    )

    filtered = df[df["sector"] == sector]
    filtered = filtered[["metrics", "Weight"]]

    if filtered.empty:
        raise ValueError(f"No weights found for sector '{sector}'.")

    return filtered

def get_sector_for_ticker(ticker: str) -> str:
    """
    Returns the sector for a given ticker symbol.

    Parameters:
    - ticker (str): The ticker symbol to look up.

    Returns:
    - str: The sector associated with the ticker.
    """
    tickers_sector = get_tickers(columns=['ticker', 'sector'])
    result = tickers_sector.filter(pl.col('ticker') == ticker).select('sector').to_series().to_list()

    if not result:
        raise ValueError(f"Ticker '{ticker}' not found.")

    sector = result[0]

    return sector

def get_market_metrics(sector: str, year: int | None = None, file_path: str = 'financial_data/metrics_by_sectors.xlsx') -> pd.DataFrame:
    """
    Loads and filters market metrics for a given sector, optionally by year.
    If year is None, returns mean market value grouped by metrics, including sector.

    Parameters:
    - sector (str): Sector name to filter by.
    - year (int | None): Year to filter by. If None, aggregates over all years.
    - file_path (str): Path to the Excel file.

    Returns:
    - pd.DataFrame: Filtered or aggregated DataFrame including 'sector'.
    """
    df = pd.read_excel(file_path)

    sector_df = df.query("sector == @sector")

    if sector_df.empty:
        raise ValueError(f"No data found for sector '{sector}'.")

    if year is not None:
        filtered_df = sector_df.query("time == @year")
        if filtered_df.empty:
            raise ValueError(f"No data found for sector '{sector}' in year {year}.")
        return filtered_df[["sector", "metrics", "market_value", "time"]]
    else:
        grouped = (
            sector_df
            .groupby(["sector", "metrics"], dropna=False, sort=False)
            .agg(mean_market_value=("market_value", "mean"))
            .reset_index()
        )
        return grouped

def flatten_weights(weights: dict) -> dict:
    """
    Flattens sector weights.
    Supports both grouped (by category) and flat dictionaries.
    
    Example:
        Input (grouped):
        {
            "Profitability & Margins": {"GrossMargin": 10, "OperatingMargin": 12},
            "Return": {"ROA": 10, "ROE": 12}
        }
        
        Output:
        {
            "GrossMargin": 10, "OperatingMargin": 12,
            "ROA": 10, "ROE": 12
        }
    """
    try:
        flat = {}
        for key, value in weights.items():
            if isinstance(value, dict):  # category grouping
                flat.update(value)
            else:  # already flat
                flat[key] = value
        return flat
    except Exception as e:
        print(f"Error flattening weights: {e}")
        return {}



# def weights_to_df(sector_metric_weights: dict) -> pd.DataFrame:
#     """
#     Converts sector_metric_weights dictionary into a tidy DataFrame.

#     Parameters:
#         sector_metric_weights (dict): Dictionary of sectors and their metric weights.

#     Returns:
#         pd.DataFrame: DataFrame with columns [sector, metric, weight]
#     """
#     try:
#         records = []
#         for sector, metrics in sector_metric_weights.items():
#             for metric, weight in metrics.items():
#                 records.append({
#                     "sector": sector,
#                     "metric": metric,
#                     "weight": weight
#                 })
#         return pd.DataFrame(records)
#     except Exception as e:
#         print(f"Error converting weights to DataFrame: {e}")
#         return pd.DataFrame(columns=["sector", "metric", "weight"])

# export_to_xlsx(
#     weights_to_df(sector_metric_weights).pivot(index='sector', columns='metric', values='weight').reset_index(),
#     'financialtools/data/weights.xlsx',
#     'sheet1'
# )

# def preprocess_df(df, ticker):
#     """
#     Preprocesses the input DataFrame by:
#     - Filtering rows for the specified ticker
#     - Extracting the year from the 'time' column
#     - Reordering columns to place 'time' last

#     Parameters:
#         df (pd.DataFrame): Original DataFrame
#         ticker (str): Ticker symbol to filter by

#     Returns:
#         pd.DataFrame: Preprocessed DataFrame
#     """
#     try:
#         return (
#             pl.from_pandas(df)
#             .filter(pl.col("ticker") == ticker)
#             .with_columns(pl.col("time").dt.year().alias("time"))
#             .select([col for col in df.columns if col != "time"] + ["time"])
#             .to_pandas()
#         )
#     except Exception as e:
#         print(f"Error preprocessing data for ticker {ticker}: {e}")
#         return pd.DataFrame()  # Return empty DataFrame on failure

# def get_fundamental_output(df, ticker, weights):
#     """
#     Evaluates fundamental metrics for a given ticker using the FundamentalTraderAssistant.

#     Parameters:
#         df (pd.DataFrame): Original DataFrame
#         ticker (str): Ticker symbol to evaluate
#         weights (dict): Grouped weights for evaluation

#     Returns:
#         dict: Dictionary containing evaluation results
#     """
#     try:
#         # processed_df = preprocess_df(df, ticker)
#         processed_df = df[df['ticker'] == ticker]
#         print(processed_df)
#         if processed_df.empty:
#             raise ValueError("Processed DataFrame is empty.")
#         assistant = FundamentalTraderAssistant(data=processed_df, weights=weights)
#         return assistant.evaluate()
#     except Exception as e:
#         print(f"Error evaluating ticker {ticker}: {e}")
#         return {
#             'metrics': pd.DataFrame(),
#             'eval_metrics': pd.DataFrame(),
#             'composite_scores': pd.DataFrame(),
#             'red_flags': pd.DataFrame(),
#             'raw_red_flags': pd.DataFrame()
#         }

# def merge_results(results, key):
#     """
#     Merges a specific key from multiple result dictionaries into a single DataFrame.

#     Parameters:
#         results (list): List of result dictionaries
#         key (str): Key to extract and merge

#     Returns:
#         pd.DataFrame: Concatenated DataFrame for the specified key
#     """
#     try:
#         return pd.concat([result.get(key) for result in results], ignore_index=True)
#     except Exception as e:
#         print(f"Error merging results for key '{key}': {e}")
#         return pd.DataFrame()

# def get_ticker_list():

#     df = pd.read_excel('financialtools/data/metrics.xlsx')
#     df.columns = df.columns.str.lower().str.replace(" ", "_")

#     # Get unique tickers
#     try:
#         tickers = (
#             pl.from_pandas(df)
#             .select("ticker")
#             .unique()
#             .get_column("ticker")
#             .to_list()
#         )
#     except Exception as e:
#         print(f"Error extracting tickers: {e}")
#         tickers = []

#     return tickers

# def get_fin_data(ticker, year=None):
#     def load_and_filter(path, year_filter=False):
#         df = pl.from_pandas(pd.read_excel(path)).filter(pl.col("ticker") == ticker)
#         if year_filter and year is not None:
#             df = df.filter(pl.col("time") == year)
#         return df

#     # Metrics
#     metrics_df = load_and_filter('financialtools/data/metrics.xlsx', year_filter=True).to_pandas()
#     metrics_df = metrics_df.round(2)
#     metrics = json.dumps(metrics_df.to_dict())

#     # Composite Scores
#     composite_df = load_and_filter('financialtools/data/composite_scores.xlsx', year_filter=True).to_pandas()
#     composite_scores = json.dumps(composite_df.to_dict())

#     # Red Flags
#     red_flags_df = pl.concat([
#         load_and_filter('financialtools/data/red_flags.xlsx', year_filter=True),
#         load_and_filter('financialtools/data/raw_red_flags.xlsx', year_filter=True)
#     ]).to_pandas()
#     red_flags = json.dumps(red_flags_df.to_dict())

#     return metrics, composite_scores, red_flags


def get_fin_data_year(ticker, year):
    # print(ticker)
    metrics = (pl.from_pandas(pd.read_excel('financial_data/metrics.xlsx'))
        .filter(pl.col("ticker") == ticker)
        .filter(pl.col("time") == year)
        .to_pandas())
    metrics = metrics.round(2)
    metrics = metrics.to_dict()
    metrics = json.dumps(metrics)


    composite_scores = (pl.from_pandas(pd.read_excel('financial_data/composite_scores.xlsx'))
        .filter(pl.col("ticker") == ticker)
        .to_pandas())
    composite_scores = composite_scores.to_dict()
    composite_scores = json.dumps(composite_scores)


    red_flags = pl.concat([
        (pl.from_pandas(pd.read_excel('financial_data/red_flags.xlsx'))
            .filter(pl.col("ticker") == ticker)
            .filter(pl.col("time") == year)
            ),
        (pl.from_pandas(pd.read_excel('financial_data/raw_red_flags.xlsx'))
            .filter(pl.col("ticker") == ticker)
            .filter(pl.col("time") == year)
            )]
    ).to_pandas()
    red_flags = red_flags.to_dict()
    red_flags = json.dumps(red_flags)

    return metrics, composite_scores, red_flags


import os

def create_newbatch_folder(file_name, batch_job_id):
    batch_files_folder = 'batch_files/'
    batch_files_folder_task = str(batch_files_folder)+str(batch_job_id)
    os.makedirs(batch_files_folder_task, exist_ok=True)
    new_name = batch_files_folder_task+str('/')+str('input.jsonl')
    os.rename(file_name, new_name)