import os
import json
import logging
import time
from typing import List, Union, Optional

import pandas as pd
import polars as pl
import numpy as np
from financialtools.exceptions import SectorNotFoundError
# from financialtools.processor import FundamentalTraderAssistant
from financialtools.config import sector_metric_weights

_logger = logging.getLogger(__name__)

def export_to_csv(df, path):
        """Public method to export merged data to CSV."""
        try:
            df.to_csv(path, index=False)
            print(f"Data exported to {path}")
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            
def export_to_xlsx(df, path, sheet_name):
        """Export a DataFrame to an Excel (.xlsx) file."""
        try:
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Data exported to {path}")
        except Exception as e:
            print(f"Error exporting to Excel: {e}")

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


def get_sector_for_ticker(
    ticker: str,
    sector_file: str = "financialtools/data/sector_ticker.txt",
) -> str:
    """
    Returns the sector for a given ticker symbol.

    Parameters:
    - ticker (str): The ticker symbol to look up.
    - sector_file (str): Path to the tab-separated sector mapping file.
      Defaults to the bundled file; pass a custom path for external consumers.

    Returns:
    - str: The sector associated with the ticker.

    Raises:
    - SectorNotFoundError: if the ticker is absent from the file.
    - FileNotFoundError: if sector_file does not exist.
    """
    tickers_sector = get_tickers(filepath=sector_file, columns=['ticker', 'sector'])
    result = tickers_sector.filter(pl.col('ticker') == ticker).select('sector').to_series().to_list()

    if not result:
        raise SectorNotFoundError(f"Ticker '{ticker}' not found in sector mapping.")

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
        raise SectorNotFoundError(f"No data found for sector '{sector}'.")

    if year is not None:
        filtered_df = sector_df.query("time == @year")
        if filtered_df.empty:
            raise SectorNotFoundError(f"No data found for sector '{sector}' in year {year}.")
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




def get_ticker_profile(ticker: str) -> pd.DataFrame:
    """
    Fetches key profile information for a given stock ticker from Yahoo Finance.

    Parameters:
    - ticker (str): The stock ticker symbol (e.g., 'FCT.MI').

    Returns:
    - pd.DataFrame: A single-row DataFrame with selected profile fields.
    """
    import yfinance as yf  # deferred: yfinance is only required for this function
    stock = yf.Ticker(ticker)
    info = stock.info

    data = {
        "shortName": info.get("shortName"),
        "industry": info.get("industry"),
        "sectorKey": info.get("sectorKey"),
        "beta": info.get("beta"),
        "longBusinessSummary": info.get("longBusinessSummary")
    }

    return pd.DataFrame([data])


def enrich_tickers(df: pd.DataFrame, ticker_column: str = "ticker") -> pd.DataFrame:
    """
    Applies get_ticker_profile to each ticker in the DataFrame and combines results.

    Parameters:
    - df (pd.DataFrame): Input DataFrame with a column of ticker symbols.
    - ticker_column (str): Name of the column containing ticker symbols.

    Returns:
    - pd.DataFrame: Combined DataFrame with profile info for each ticker.
    """
    profiles = []
    for ticker in df[ticker_column]:
        try:
            profile_df = get_ticker_profile(ticker)
            profile_df["ticker"] = ticker  # Add ticker for traceability
            profiles.append(profile_df)
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
        time.sleep(0.5)  # Pause to avoid overwhelming the API

    return pd.concat(profiles, ignore_index=True)


def get_fin_data(
    ticker: str,
    year: int | None = None,
    base_dir: str = 'financial_data',
    round_metrics: bool = False,
) -> tuple:
    """
    Load financial data for a ticker from Excel files and return as JSON strings.

    Args:
        ticker: Ticker symbol to filter by.
        year: If provided, filter metrics and red flags to this year only.
              Composite scores are always returned without year filtering
              (they aggregate across all years for trend visibility).
        base_dir: Directory containing the Excel files. Defaults to 'financial_data'
                  (runtime output dir). Use 'financialtools/data' for package data.
        round_metrics: If True, round metric values to 2 decimal places.

    Returns:
        Tuple of (metrics_json, composite_scores_json, red_flags_json).
    """
    import os

    def _load(filename: str, year_filter: bool = False) -> pl.DataFrame:
        path = os.path.join(base_dir, filename)
        df = pl.from_pandas(pd.read_excel(path)).filter(pl.col("ticker") == ticker)
        if year_filter and year is not None:
            df = df.filter(pl.col("time") == year)
        return df

    metrics_df = _load('metrics.xlsx', year_filter=True).to_pandas()
    if round_metrics:
        metrics_df = metrics_df.round(2)
    metrics = json.dumps(metrics_df.to_dict())

    # Composite scores: no year filter — callers typically want the full trend.
    composite_df = _load('composite_scores.xlsx', year_filter=False).to_pandas()
    composite_scores = json.dumps(composite_df.to_dict())

    red_flags_df = pl.concat([
        _load('red_flags.xlsx', year_filter=True),
        _load('raw_red_flags.xlsx', year_filter=True),
    ]).to_pandas()
    red_flags = json.dumps(red_flags_df.to_dict())

    return metrics, composite_scores, red_flags


def get_fin_data_year(ticker: str, year: int) -> tuple:
    """Backward-compatible alias for get_fin_data with runtime output dir and rounded metrics."""
    return get_fin_data(ticker, year=year, base_dir='financial_data', round_metrics=True)


def list_evaluated_tickers(base_dir: str = "financial_data") -> list[str]:
    """
    Return a sorted list of tickers present in composite_scores.xlsx.

    This is the canonical way for tools and agents to discover which tickers
    have been evaluated and are ready for analysis.

    Args:
        base_dir: Directory containing the Excel output files.
                  Defaults to 'financial_data' (runtime output dir).

    Returns:
        Sorted list of ticker strings. Returns [] on any I/O or parsing failure.
    """
    try:
        path = os.path.join(base_dir, "composite_scores.xlsx")
        df = pd.read_excel(path, sheet_name="sheet1")
        return sorted(df["ticker"].dropna().unique().tolist())
    except Exception as exc:
        _logger.warning(
            f"list_evaluated_tickers: could not read {base_dir}/composite_scores.xlsx — {exc}"
        )
        return []


def create_newbatch_folder(file_name, batch_job_id):
    """
    Move `file_name` into a per-job subfolder of batch_files/.

    Note: `batch_files/` is resolved relative to the caller's working directory.
    Pass an absolute path for `file_name` to avoid cwd-dependent behaviour.
    """
    batch_files_folder = 'batch_files'
    batch_files_folder_task = os.path.join(batch_files_folder, str(batch_job_id))
    os.makedirs(batch_files_folder_task, exist_ok=True)
    new_name = os.path.join(batch_files_folder_task, 'input.jsonl')
    os.rename(file_name, new_name)