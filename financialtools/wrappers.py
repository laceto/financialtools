import re
import time
import pandas as pd
import polars as pl
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from financialtools.utils import export_to_xlsx
from financialtools.processor import Downloader, FundamentalTraderAssistant, _empty_result


import logging
import traceback

# Log directory is anchored to the package root, not the caller's cwd.
# This ensures log files always land in <repo_root>/logs/ regardless of where
# the module is imported from (tests/, notebooks/, scripts/, CI, etc.).
import os as _os
_LOGS_DIR = _os.path.join(_os.path.dirname(__file__), '..', 'logs')

# Logger instance — created at import time (cheap, no I/O).
# File handlers are added lazily by _configure_logging() on first use so that
# importing DownloaderWrapper in tests does not create log files as a side
# effect (M5 fix).
logger = logging.getLogger('TickerDownloader')
logger.setLevel(logging.DEBUG)

_handlers_configured = False


def _configure_logging() -> None:
    """
    Attach file handlers to the TickerDownloader logger on first use.

    Called lazily so that unit tests which import wrappers without intending
    to perform any downloads do not trigger log-directory creation or file
    handle allocation.  Safe to call multiple times — subsequent calls are
    no-ops guarded by the module-level ``_handlers_configured`` flag.
    """
    global _handlers_configured
    if _handlers_configured:
        return
    _os.makedirs(_LOGS_DIR, exist_ok=True)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    info_handler = logging.FileHandler(_os.path.join(_LOGS_DIR, 'info.log'))
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)

    error_handler = logging.FileHandler(_os.path.join(_LOGS_DIR, 'error.log'))
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    debug_handler = logging.FileHandler(_os.path.join(_LOGS_DIR, 'debug.log'))
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(formatter)

    logger.addHandler(info_handler)
    logger.addHandler(error_handler)
    logger.addHandler(debug_handler)
    _handlers_configured = True



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

        Enrichment (mirrors _download_and_evaluate in agents/_tools/data_tools.py)
        --------------------------------------------------------------------------
        After downloading merged financials, calls get_info_data() to attach two
        columns to the result:
          - company_name : lowercased longName from yfinance info, falls back to ticker
          - sector       : lowercased, hyphenated sectorKey (e.g. "financial-services"),
                           falls back to "default"
        """
        _configure_logging()
        logger.info(f"[{ticker}] Starting download")
        try:
            time.sleep(2)  # avoid hitting rate limits
            processor = Downloader.from_ticker(ticker)
            merged_data = processor.get_merged_data()
            merged_data.columns = merged_data.columns.str.lower().str.replace(" ", "_")
            merged_data = DownloaderWrapper._preprocess_df(merged_data)

            # ── Enrich: company name ─────────────────────────────────────────
            info_df = processor.get_info_data()
            if not info_df.empty and "longName" in info_df.columns:
                company_name = info_df["longName"].str.lower().to_string(index=False).strip()
            else:
                company_name = ticker.lower()
                logger.warning(f"[{ticker}] longName not found in info; using ticker as name")

            # ── Enrich: sector ───────────────────────────────────────────────
            if not info_df.empty and "sector" in info_df.columns:
                raw = info_df["sector"].str.lower().to_string(index=False)
                sector = re.sub(r" ", "-", raw.strip())
            else:
                sector = "default"
                logger.warning(f"[{ticker}] sector not found in info; using 'default'")

            merged_data["company_name"] = company_name
            merged_data["sector"] = sector

            logger.info(f"[{ticker}] Download and processing successful")
            return merged_data
        except Exception as e:
            logger.error(f"[{ticker}] Error: {e}")
            logger.debug(f"[{ticker}] Traceback:\n{traceback.format_exc()}")
            return None


    @staticmethod
    def _download_multiple_tickers(
        tickers: list[str],
        max_workers: int = 4,
    ) -> pd.DataFrame | None:
        """
        Internal helper: Download and combine data for multiple tickers in parallel.

        Uses ``ThreadPoolExecutor`` so network I/O for different tickers overlaps.
        Each worker calls ``_download_single_ticker``, which already handles its
        own exceptions and returns ``None`` on failure — no ticker failure
        propagates to other workers or to the caller.

        Parameters
        ----------
        tickers     : List of ticker symbols to download.
        max_workers : Thread pool size (default 4). Keep this low — yfinance
                      is rate-sensitive and each thread may trigger a brief
                      ``time.sleep(2)`` inside ``_download_single_ticker``.

        Returns
        -------
        pd.DataFrame
            All successful downloads concatenated, in completion order.
        None
            If every ticker failed.
        """
        _configure_logging()
        fin_data: list[pd.DataFrame] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(DownloaderWrapper._download_single_ticker, t): t
                for t in tickers
            }
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    # _download_single_ticker should never raise, but guard anyway.
                    logger.error("[%s] Unexpected exception in download worker: %s", ticker, exc, exc_info=True)
                    result = None
                if result is not None:
                    fin_data.append(result)

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

    def __init__(self, df: pd.DataFrame, weights: pd.DataFrame):
        """
        Initialize the evaluator.

        Parameters:
            df (pd.DataFrame): Full DataFrame with all tickers' data.
            weights (pd.DataFrame): Sector weights DataFrame with columns
                ``sector``, ``metrics``, ``weights`` — as returned by
                ``financialtools.analysis.build_weights(sector)``.

                The previous type hint was ``dict``, which caused a runtime
                ``AttributeError`` because ``FundamentalTraderAssistant``
                calls ``weights['sector'].dropna()`` — a DataFrame method
                that plain dicts do not have.
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
            logger.error(f"[{ticker}] evaluate_single failed: {e}", exc_info=True)
            return _empty_result()  # single source of truth from processor.py

    def evaluate_multiple(self, tickers: list, parallel: bool = True, max_workers: int = 5) -> dict:
        """
        Evaluate fundamentals for multiple tickers.

        Parameters:
            tickers (list): List of ticker symbols.
            parallel (bool): Run evaluations in parallel (default=True).
            max_workers (int): Thread pool size for parallel runs (default=5).
                Keep this low — each thread makes network calls to yfinance.

        Returns:
            dict: Results for all tickers keyed by ticker.
        """
        results = {}

        if parallel:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self.evaluate_single, t): t for t in tickers}
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        results[ticker] = future.result()
                    except Exception as e:
                        # Use _empty_result() — not None — so that merge_results()
                        # can safely call result.get(key) on every entry without
                        # a NoneType AttributeError.
                        logger.error(
                            "[%s] Parallel evaluation failed: %s", ticker, e, exc_info=True
                        )
                        results[ticker] = _empty_result()
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

    Design note:
        Each value in results must be a dict (as returned by evaluate_single /
        _empty_result) — never None. The isinstance guard below is a defensive
        last-resort check; evaluate_multiple guarantees this contract after S3 fix.
    """
    try:
        frames = [
            df
            for result in results.values()
            if isinstance(result, dict)
            for df in (result.get(key),)
            if isinstance(df, pd.DataFrame) and not df.empty
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
        Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
            metrics, eval_metrics, composite_scores, red_flags
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
    raw_red_flags = read_and_filter("raw_red_flags")

    red_flags = pd.concat([red_flags, raw_red_flags], axis=0, ignore_index=True)

    return metrics, eval_metrics, composite_scores, red_flags