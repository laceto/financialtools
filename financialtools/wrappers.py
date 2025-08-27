import time
import pandas as pd
import polars as pl
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from financialtools.utils import export_to_xlsx
from financialtools.processor import Downloader, FundamentalTraderAssistant


import logging
import traceback

# Create logger
logger = logging.getLogger('TickerDownloader')
logger.setLevel(logging.DEBUG)

# Formatter with timestamp and message
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Info handler
info_handler = logging.FileHandler('logs/info.log')
info_handler.setLevel(logging.INFO)
info_handler.setFormatter(formatter)

# Error handler
error_handler = logging.FileHandler('logs/error.log')
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(formatter)

# Debug handler
debug_handler = logging.FileHandler('logs/debug.log')
debug_handler.setLevel(logging.DEBUG)
debug_handler.setFormatter(formatter)

# Add handlers
logger.addHandler(info_handler)
logger.addHandler(error_handler)
logger.addHandler(debug_handler)



class DownloaderWrapper:

    @staticmethod
    def _preprocess_df(df):
        """
        Preprocesses the input DataFrame by:
        - Extracting the year from the 'time' column
        - Reordering columns to place 'time' last

        Parameters:
            df (pd.DataFrame): Original DataFrame

        Returns:
            pd.DataFrame: Preprocessed DataFrame
        """
        try:
            return (
                pl.from_pandas(df)
                .with_columns(pl.col("time").dt.year().alias("time"))
                .select([col for col in df.columns if col != "time"] + ["time"])
                .to_pandas()
            )
        except Exception as e:
            print(f"Error preprocessing data: {e}")
            return pd.DataFrame()  # Return empty DataFrame on failure
    
    @staticmethod
    def _download_single_ticker(ticker: str) -> pd.DataFrame | None:
        """
        Internal helper: Download and return data for a single ticker.
        Returns None if download fails.
        Logs to multiple files with timestamp and ticker context.
        """
        logger.info(f"[{ticker}] Starting download")
        try:
            time.sleep(2)  # avoid hitting rate limits
            processor = Downloader.from_ticker(ticker)
            merged_data = processor.get_merged_data()
            merged_data.columns = merged_data.columns.str.lower().str.replace(" ", "_")
            merged_data = DownloaderWrapper._preprocess_df(merged_data)
            logger.info(f"[{ticker}] Download and processing successful")
            return merged_data
        except Exception as e:
            logger.error(f"[{ticker}] Error: {e}")
            logger.debug(f"[{ticker}] Traceback:\n{traceback.format_exc()}")
            return None


    @staticmethod
    def _download_multiple_tickers(tickers: list[str]) -> pd.DataFrame | None:
        """
        Internal helper: Download and combine data for multiple tickers.
        Returns None if all downloads fail.
        """
        fin_data = []
        for ticker in tickers:
            data = DownloaderWrapper._download_single_ticker(ticker)
            if data is not None:
                fin_data.append(data)

        if not fin_data:
            return None
        return pd.concat(fin_data, ignore_index=True)

    @staticmethod
    def download_data(tickers: str | list[str]) -> pd.DataFrame | None:
        """
        Public wrapper: Download data for one or multiple tickers.

        Parameters
        ----------
        tickers : str or list[str]
            - If str: download data for a single ticker
            - If list[str]: download and merge data for all tickers

        Returns
        -------
        pd.DataFrame or None
            - DataFrame with ticker data if successful
            - None if all downloads fail
        """
        if isinstance(tickers, str):
            return DownloaderWrapper._download_single_ticker(tickers)
        elif isinstance(tickers, list):
            return DownloaderWrapper._download_multiple_tickers(tickers)
        else:
            raise TypeError("tickers must be a str or list of str")
        





class FundamentalEvaluator:
    """
    Wrapper around FundamentalTraderAssistant to evaluate fundamentals
    for single or multiple tickers.
    """

    def __init__(self, df: pd.DataFrame, weights: dict):
        """
        Initialize the evaluator.

        Parameters:
            df (pd.DataFrame): Full DataFrame with all tickers' data.
            weights (dict): Grouped weights for evaluation.
        """
        self.df = df
        self.weights = weights

    def evaluate_single(self, ticker: str) -> dict:
        """
        Evaluate fundamentals for a single ticker.

        Parameters:
            ticker (str): Ticker symbol to evaluate.

        Returns:
            dict: Dictionary containing evaluation results.
        """
        try:
            processed_df = self.df[self.df["ticker"] == ticker]
            if processed_df.empty:
                raise ValueError("Processed DataFrame is empty.")

            assistant = FundamentalTraderAssistant(
                data=processed_df, weights=self.weights
            )
            return assistant.evaluate()

        except Exception as e:
            print(f"Error evaluating ticker '{ticker}': {e}")
            return {
                "metrics": pd.DataFrame(),
                "eval_metrics": pd.DataFrame(),
                "composite_scores": pd.DataFrame(),
                "red_flags": pd.DataFrame(),
                "raw_red_flags": pd.DataFrame(),
            }

    def evaluate_multiple(self, tickers: list, parallel: bool = True) -> dict:
        """
        Evaluate fundamentals for multiple tickers.

        Parameters:
            tickers (list): List of ticker symbols.
            parallel (bool): Run evaluations in parallel (default=True).

        Returns:
            dict: Results for all tickers keyed by ticker.
        """
        results = {}

        if parallel:
            with ThreadPoolExecutor() as executor:
                futures = {executor.submit(self.evaluate_single, t): t for t in tickers}
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        results[ticker] = future.result()
                    except Exception as e:
                        print(f"Parallel evaluation failed for {ticker}: {e}")
                        results[ticker] = None
        else:
            for ticker in tickers:
                results[ticker] = self.evaluate_single(ticker)

        return results


def merge_results(results: dict, key: str) -> pd.DataFrame:
    """
    Merges a specific key from multiple result dictionaries into a single DataFrame.

    Parameters:
        results (dict): Dict of {ticker: result_dict}
        key (str): Key to extract and merge (e.g., 'composite_scores')

    Returns:
        pd.DataFrame: Concatenated DataFrame for the specified key
    """
    try:
        frames = [
            result.get(key)
            for result in results.values()
            if result is not None and not result.get(key).empty
        ]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    except Exception as e:
        print(f"Error merging results for key '{key}': {e}")
        return pd.DataFrame()
    

def export_financial_results(results, output_dir="financial_data", sheet_name="sheet1"):
    """
    Merges result dictionaries by predefined keys and exports each to an Excel file.

    Parameters:
        results (list): List of result dictionaries.
        output_dir (str): Directory to save Excel files.
        sheet_name (str): Name of the Excel sheet.
    """
    import os

    keys = [
        "metrics",
        "eval_metrics",
        "composite_scores",
        "red_flags",
        "raw_red_flags"
    ]

    os.makedirs(output_dir, exist_ok=True)

    for key in keys:
        try:
            df = merge_results(results, key)
            export_to_xlsx(
                df=df,
                path=f"{output_dir}/{key}.xlsx",
                sheet_name=sheet_name
            )
        except Exception as e:
            print(f"Failed to export '{key}': {e}")


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
            df = df.round(4)

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