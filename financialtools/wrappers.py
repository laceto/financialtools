import pandas as pd
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from financialtools.utils import build_weights, export_to_xlsx, resolve_sector, RateLimiter
from financialtools.processor import Downloader, FundamentalMetricsEvaluator
from financialtools.evaluator import empty_result
from financialtools.exceptions import DownloadError


import logging
import traceback

# Log directory — configurable via FINANCIALTOOLS_LOG_DIR env var so that
# containerised / read-only deployments can redirect logs without code changes.
# Falls back to <repo_root>/logs/ anchored to the package root.
import os as _os
_LOGS_DIR = _os.environ.get(
    "FINANCIALTOOLS_LOG_DIR",
    _os.path.join(_os.path.dirname(__file__), '..', 'logs'),
)

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

    Failure handling
    ----------------
    If the log directory cannot be created (e.g. read-only filesystem in Docker),
    the function catches ``OSError`` and falls back to a ``StreamHandler`` (stderr)
    rather than raising.  A single WARNING is emitted explaining the fallback and
    how to override the log path via ``FINANCIALTOOLS_LOG_DIR``.
    """
    global _handlers_configured
    if _handlers_configured:
        return

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    try:
        _os.makedirs(_LOGS_DIR, exist_ok=True)

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

    except OSError as exc:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.DEBUG)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
        logger.warning(
            "Cannot create log directory %r (%s) — falling back to stderr logging. "
            "Set FINANCIALTOOLS_LOG_DIR to a writable path to enable file logging.",
            _LOGS_DIR, exc,
        )

    _handlers_configured = True



def _preprocess_df(df: pd.DataFrame) -> pd.DataFrame:
    """Extract year from 'time' column and reorder columns to place 'time' last."""
    try:
        out = df.copy()
        out["time"] = pd.to_datetime(out["time"]).dt.year
        cols = [c for c in df.columns if c != "time"] + ["time"]
        return out[cols]
    except Exception as e:
        logger.error("Error preprocessing data: %s", e, exc_info=True)
        return pd.DataFrame()


def _download_single_ticker(
    ticker: str,
    limiter: RateLimiter | None = None,
) -> pd.DataFrame | None:
    """Download and return merged financials for one ticker, enriched with company_name and sector.

    Returns None on failure — never raises.

    Parameters
    ----------
    ticker  : yfinance ticker symbol
    limiter : optional RateLimiter — acquire() is called before the download so
              concurrent workers share a single rate budget. When None (single-
              ticker path), no rate limiting is applied.

    Enrichment
    ----------
    company_name : lowercased longName from yfinance info, falls back to ticker
    sector       : lowercased hyphenated sectorKey (e.g. "financial-services"),
                   falls back to "default"
    """
    _configure_logging()
    logger.info(f"[{ticker}] Starting download")
    try:
        if limiter is not None:
            limiter.acquire()
        processor = Downloader.from_ticker(ticker)
        merged_data = processor.get_merged_data()
        merged_data.columns = merged_data.columns.str.lower().str.replace(" ", "_")
        merged_data = _preprocess_df(merged_data)

        info_df = processor.get_info_data()
        if not info_df.empty and "longName" in info_df.columns:
            company_name = info_df["longName"].iloc[0].lower().strip()
        else:
            company_name = ticker.lower()
            logger.warning(f"[{ticker}] longName not found in info; using ticker as name")

        merged_data["company_name"] = company_name
        merged_data["sector"] = resolve_sector(info_df)

        logger.info(f"[{ticker}] Download and processing successful")
        return merged_data
    except Exception as e:
        logger.error(f"[{ticker}] Error: {e}")
        logger.debug(f"[{ticker}] Traceback:\n{traceback.format_exc()}")
        return None


def _download_multiple_tickers(
    tickers: list[str],
    max_workers: int = 4,
    limiter: RateLimiter | None = None,
) -> pd.DataFrame | None:
    """Download and combine data for multiple tickers in parallel.

    Uses ThreadPoolExecutor so network I/O overlaps across tickers.
    A shared RateLimiter (default: 20 calls/minute) is passed to each worker
    so all concurrent threads draw from the same rate budget — replacing the
    old per-worker time.sleep(2) which added fixed latency regardless of load.

    Each worker calls _download_single_ticker, which returns None on failure —
    no single ticker failure propagates to others or the caller.

    Parameters
    ----------
    tickers     : list of yfinance ticker symbols
    max_workers : thread pool size (default 4)
    limiter     : optional RateLimiter override; defaults to RateLimiter(per_minute=20)

    Returns concatenated DataFrame of all successful downloads, or None if all fail.
    """
    _configure_logging()
    if limiter is None:
        limiter = RateLimiter(per_minute=20)
    fin_data: list[pd.DataFrame] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_download_single_ticker, t, limiter): t
            for t in tickers
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.error("[%s] Unexpected exception in download worker: %s", ticker, exc, exc_info=True)
                result = None
            if result is not None:
                fin_data.append(result)

    if not fin_data:
        return None
    return pd.concat(fin_data, ignore_index=True)


def download_data(tickers: str | list[str]) -> pd.DataFrame:
    """Download merged financials for one or multiple tickers.

    Parameters
    ----------
    tickers : str or list[str]

    Returns
    -------
    pd.DataFrame
        All downloaded rows concatenated.

    Raises
    ------
    DownloadError
        If all downloads fail.
    TypeError
        If tickers is not a str or list[str].
    """
    if isinstance(tickers, str):
        result = _download_single_ticker(tickers)
    elif isinstance(tickers, list):
        result = _download_multiple_tickers(tickers)
    else:
        raise TypeError("tickers must be a str or list of str")

    if result is None:
        label = tickers if isinstance(tickers, str) else f"{len(tickers)} tickers"
        raise DownloadError(
            f"download_data({label!r}) failed — all downloads returned no data. "
            "Check logs for per-ticker errors."
        )
    return result


class DownloaderWrapper:
    """Backward-compatible shim — use module-level download_data() directly."""

    __slots__ = ()
    download_data = staticmethod(download_data)
        





class FundamentalEvaluator:
    """
    Wrapper around FundamentalMetricsEvaluator to evaluate fundamentals
    for single or multiple tickers.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        weights: pd.DataFrame | None = None,
        sector: str | None = None,
    ):
        """
        Initialize the evaluator.

        Exactly one of ``weights`` or ``sector`` must be provided.

        Parameters
        ----------
        df : pd.DataFrame
            Full DataFrame with all tickers' data.
        weights : pd.DataFrame, optional
            Sector weights with columns ``sector``, ``metrics``, ``weights``
            — as returned by ``build_weights()``. Use this for custom weights.
        sector : str, optional
            yfinance sectorKey (e.g. ``"technology"``). When supplied,
            ``build_weights(sector)`` is called internally — no need to import
            or call it separately. See ``list_sectors()`` for valid values.
        """
        if weights is None and sector is None:
            raise ValueError("Provide either 'weights' (DataFrame) or 'sector' (str).")
        if weights is not None and sector is not None:
            raise ValueError("Provide only one of 'weights' or 'sector', not both.")

        self.df = df
        self.weights = weights if weights is not None else build_weights(sector)

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

            assistant = FundamentalMetricsEvaluator(
                data=processed_df, weights=self.weights
            )
            return assistant.evaluate()

        except Exception as e:
            logger.error(f"[{ticker}] evaluate_single failed: {e}", exc_info=True)
            return empty_result()  # single source of truth from processor.py

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
                        # Use empty_result() — not None — so that merge_results()
                        # can safely call result.get(key) on every entry without
                        # a NoneType AttributeError.
                        logger.error(
                            "[%s] Parallel evaluation failed: %s", ticker, e, exc_info=True
                        )
                        results[ticker] = empty_result()
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
        empty_result()) — never None. The isinstance guard below is a defensive
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
        logger.error("Error merging results for key %r: %s", key, e, exc_info=True)
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
            logger.error("Failed to export %r: %s", key, e, exc_info=True)


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
            logger.error("Error reading %s: %s", filename, e, exc_info=True)
            return pd.DataFrame()

    metrics = read_and_filter("metrics")
    eval_metrics = read_and_filter("eval_metrics")
    composite_scores = read_and_filter("composite_scores")
    red_flags = read_and_filter("red_flags")
    raw_red_flags = read_and_filter("raw_red_flags")

    red_flags = pd.concat([red_flags, raw_red_flags], axis=0, ignore_index=True)

    return metrics, eval_metrics, composite_scores, red_flags