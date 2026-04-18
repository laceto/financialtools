import json
import logging
import re
import threading
import time

import pandas as pd

from financialtools.config import sec_sector_metric_weights

_logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Thread-safe sliding-window rate limiter.

    Enforces three independent windows simultaneously:
      per_minute  — max calls within any 60-second window
      per_hour    — max calls within any 3600-second window
      per_day     — max calls within any 86400-second window

    acquire() blocks until all three windows have a free slot, then records
    the call timestamp atomically.

    Design invariant
    ----------------
    The internal lock is held only during the window-check and the atomic
    ``self.calls.append`` on success.  It is *never* held during ``sleep()``
    so that other threads can check their own windows concurrently (C1 fix).

    Usage
    -----
    limiter = RateLimiter(per_minute=30)
    limiter.acquire()     # blocks if limit exceeded
    make_api_call()
    """

    def __init__(self, per_minute: int = 60, per_hour: int = 360, per_day: int = 8000):
        self.per_minute = per_minute
        self.per_hour   = per_hour
        self.per_day    = per_day
        self.calls: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """
        Block until a call is permissible under all three rate limits.

        Uses sliding-window checks. Refreshes timestamps after each sleep so
        stale values do not cause limit overruns.

        Invariant: self._lock is held only while reading/writing self.calls,
        never during sleep(). Holding the lock across sleep() would serialise
        all threads — they would queue on the lock rather than on the rate
        window, defeating the purpose of the limiter entirely.
        """
        while True:
            with self._lock:
                now = time.time()
                # Prune calls older than 24 h to bound list growth.
                self.calls = [t for t in self.calls if now - t < 86400]

                calls_last_minute = [t for t in self.calls if now - t < 60]
                calls_last_hour   = [t for t in self.calls if now - t < 3600]

                wait = 0.0
                if len(calls_last_minute) >= self.per_minute and calls_last_minute:
                    wait = max(wait, 60 - (now - calls_last_minute[0]))
                if len(calls_last_hour) >= self.per_hour and calls_last_hour:
                    wait = max(wait, 3600 - (now - calls_last_hour[0]))
                if len(self.calls) >= self.per_day and self.calls:
                    wait = max(wait, 86400 - (now - self.calls[0]))

                if wait <= 0.0:
                    # All windows have a free slot — record the call and return.
                    self.calls.append(time.time())
                    return

            # Lock released before sleeping so other threads can check their
            # own windows concurrently. Re-enter loop to recompute with fresh
            # timestamps after waking.
            time.sleep(max(0.0, wait))


def export_to_csv(df, path):
    """Export a DataFrame to a CSV file."""
    try:
        df.to_csv(path, index=False)
        _logger.info("Data exported to %s", path)
    except Exception as e:
        _logger.error("Error exporting to CSV %s: %s", path, e, exc_info=True)


def export_to_xlsx(df, path, sheet_name):
    """Export a DataFrame to an Excel (.xlsx) file."""
    try:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        _logger.info("Data exported to %s", path)
    except Exception as e:
        _logger.error("Error exporting to Excel %s: %s", path, e, exc_info=True)


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

    # Replace Inf/-Inf with None, then NaN with None so json.dumps never
    # encounters bare float('nan') or float('inf'), which are not valid JSON.
    df_clean = df.replace([float('inf'), float('-inf')], None)
    df_clean = df_clean.where(df_clean.notna(), other=None)
    df_dict = df_clean.to_dict(orient='records')
    return json.dumps(df_dict)


def build_weights(sector: str) -> pd.DataFrame:
    """Build a weights DataFrame for the given sector.

    Uses sec_sector_metric_weights (yfinance sectorKey convention, e.g. "technology").
    Falls back to 'default' if sector is not found.

    Returns pd.DataFrame with columns: sector, metrics, weights.
    """
    if sector in sec_sector_metric_weights:
        sector_weights_dict = sec_sector_metric_weights[sector]
    else:
        _logger.warning(
            "Sector '%s' not found in sec_sector_metric_weights — using 'default'. "
            "Valid sectors: %s",
            sector,
            sorted(sec_sector_metric_weights.keys()),
        )
        sector_weights_dict = sec_sector_metric_weights["default"]
    return pd.DataFrame({
        "sector":  sector,
        "metrics": list(sector_weights_dict.keys()),
        "weights": list(sector_weights_dict.values()),
    })


def list_sectors() -> list[str]:
    """Return all valid sector names accepted by build_weights().

    Uses yfinance sectorKey convention (lowercase, hyphenated), e.g. "technology",
    "financial-services". "default" is always present as a fallback.
    """
    return sorted(sec_sector_metric_weights.keys())


def resolve_sector(info_df: pd.DataFrame, fallback: str = "default") -> str:
    """Derive a sec_sector_metric_weights key from a yfinance info DataFrame.

    Lowercases the sector value and replaces spaces with dashes to match
    the yfinance sectorKey convention (e.g. "financial-services").
    Falls back to ``fallback`` with a warning when the sector column is absent.
    """
    if not info_df.empty and "sector" in info_df.columns:
        raw = info_df["sector"].iloc[0].lower()
        return re.sub(r" ", "-", raw.strip())
    _logger.warning("sector not found in info_df — using %r", fallback)
    return fallback


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
        _logger.error("Error flattening weights: %s", e, exc_info=True)
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
            _logger.error("Error fetching data for %s: %s", ticker, e, exc_info=True)
        time.sleep(0.5)  # Pause to avoid overwhelming the API

    if not profiles:
        _logger.warning("enrich_tickers: no profiles fetched — returning empty DataFrame")
        return pd.DataFrame()
    return pd.concat(profiles, ignore_index=True)
