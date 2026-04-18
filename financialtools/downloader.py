"""downloader.py — yfinance data acquisition layer.

Provides Downloader: fetches, reshapes, and merges balance sheet,
income statement, cash flow, and info data for a single ticker.

Depends on: exceptions, utils (RateLimiter), pandas, yfinance.
No compute/scoring logic — see evaluator.py for that layer.
"""
import os
import logging as _logging
from typing import List

import pandas as pd

from financialtools.exceptions import DownloadError
from financialtools.utils import RateLimiter  # noqa: F401  (re-export for callers)

_logger = _logging.getLogger(__name__)


class Downloader:
    def __init__(self, ticker, _from_factory: bool = False):
        """Internal constructor — use ``Downloader.from_ticker(ticker)`` instead.

        Direct instantiation leaves all financial data as None, causing silent
        empty-DataFrame returns from ``get_merged_data()`` and all metric methods.
        """
        if not _from_factory:
            raise TypeError(
                "Use Downloader.from_ticker(ticker) to construct a Downloader. "
                "Direct instantiation leaves financial data unloaded, which causes "
                "silent empty-DataFrame returns from get_merged_data() and evaluate()."
            )
        self.ticker = ticker
        self._balance_sheet = None
        self._income_stmt = None
        self._cashflow = None
        self._info = None

    @classmethod
    def from_ticker(cls, ticker):
        """Download and reshape all financial data for one ticker.

        Returns
        -------
        Downloader
            Fully populated instance with ``_balance_sheet``, ``_income_stmt``,
            ``_cashflow``, and ``_info`` set.

        Raises
        ------
        DownloadError
            If yfinance raises any exception during data retrieval or reshaping.
            Callers that need a soft-failure path should catch ``DownloadError``
            explicitly — do **not** rely on an empty ``Downloader`` being returned.

        Note
        ----
        This method never returns a ``Downloader`` with ``None`` internals.
        Previously it returned ``cls(ticker)`` on failure (S4 fix), which was
        indistinguishable from a valid empty-data ticker and caused silent
        downstream errors in ``get_merged_data()`` and metric computation.
        """
        import yfinance as yf

        try:
            t = yf.Ticker(ticker)
            d = cls(ticker, _from_factory=True)

            # raw data
            d._balance_sheet = cls.__reshape_fin_data(
                t.balance_sheet.reset_index().assign(ticker=ticker, docs="balance_sheet")
            )
            d._income_stmt = cls.__reshape_fin_data(
                t.income_stmt.reset_index().assign(ticker=ticker, docs="income_stmt")
            )
            d._cashflow = cls.__reshape_fin_data(
                t.cashflow.reset_index().assign(ticker=ticker, docs="cashflow")
            )

            df_info = pd.DataFrame(list(t.info.items()), columns=["key", "value"])
            df_info.insert(0, "ticker", ticker)
            df_info = df_info.pivot(index=["ticker"], columns='key', values='value').reset_index()
            d._info = df_info

            return d

        except Exception as e:
            _logger.error(f"[{ticker}] from_ticker failed: {e}", exc_info=True)
            raise DownloadError(f"[{ticker}] download failed: {e}") from e

    @staticmethod
    def __reshape_fin_data(df: pd.DataFrame) -> pd.DataFrame:
        """
        Reshape financial data DataFrame to have 'ticker', 'time', and metric columns.

        Args:
            df: Financial data DataFrame from yfinance (e.g., balance sheet).

        Returns:
            pd.DataFrame with columns 'ticker', 'time', and financial metrics, or empty on failure.
        """
        if df.empty:
            return df
        try:
            pivot_vars = ["index", "ticker", "docs"]
            value_vars = [c for c in df.columns if c not in pivot_vars]
            df = df.melt(id_vars=pivot_vars, value_vars=value_vars,
                         var_name="time", value_name="value")
            df = df.pivot_table(index=["ticker", "docs", "time"],
                                columns="index", values="value").reset_index()
            df.columns = [col.replace(' ', '_').lower() for col in df.columns]
            return df
        except Exception as e:
            _logger.error("Error reshaping financial data: %s", e, exc_info=True)
            return pd.DataFrame()

    def get_info_data(self) -> pd.DataFrame:
        """
        Retrieve stock info for the ticker.

        Returns:
            pd.DataFrame with filtered stock info (e.g., marketCap, forwardPE) or empty DataFrame if unavailable.
        """
        if self._info is None or self._info.empty:
            return pd.DataFrame()
        return self._info

    # Market-data columns pulled from _info and broadcast across all time periods.
    # Keeping this list here (not in compute_valuation_metrics) makes it the single
    # source of truth for what get_merged_data() enriches.
    _MARKET_COLS = ("marketcap", "currentprice", "sharesoutstanding")

    def get_merged_data(self) -> pd.DataFrame:
        """
        Merge balance sheet, income statement, and cash flow data for a single ticker,
        then broadcast market-data columns (marketcap, currentprice, sharesoutstanding)
        from _info across all time periods.

        Callers no longer need to manually call get_info_data() and merge — the returned
        DataFrame is fully enriched and ready for FundamentalTraderAssistant.

        Returns pd.DataFrame() on failure; never raises.
        """
        try:
            dfs = [self._balance_sheet, self._cashflow, self._income_stmt]
            dfs = [df for df in dfs if isinstance(df, pd.DataFrame) and not df.empty]
            if len(dfs) < 2:
                return pd.DataFrame()

            merged = dfs[0]
            for df in dfs[1:]:
                merged = merged.merge(df, how="left", on=["ticker", "time"])

            if merged.empty:
                return pd.DataFrame()

            if self._info is not None and not self._info.empty:
                info_lower = self._info.rename(columns=str.lower)
                available  = [c for c in self._MARKET_COLS if c in info_lower.columns]
                if available:
                    market_row = info_lower[["ticker"] + available]
                    merged = merged.merge(market_row, on="ticker", how="left")

            return merged

        except Exception as e:
            _logger.error(f"[{self.ticker}] get_merged_data failed: {e}", exc_info=True)
            return pd.DataFrame()

    @classmethod
    def combine_merged_data(cls, downloaders: List['Downloader']) -> pd.DataFrame:
        """Combine merged financial data from multiple Downloader instances."""
        try:
            dfs = []
            for d in downloaders:
                df = d.get_merged_data()
                if not df.empty:
                    dfs.append(df)
                else:
                    _logger.warning("No merged data for %s", d.ticker)

            if not dfs:
                return pd.DataFrame()

            combined = pd.concat(dfs, ignore_index=True)
            combined = combined.reindex(columns=combined.columns, fill_value=pd.NA)
            return combined

        except Exception as e:
            tickers = [d.ticker for d in downloaders]
            _logger.error(f"combine_merged_data failed for {tickers}: {e}", exc_info=True)
            return pd.DataFrame()

    @classmethod
    def combine_info_data(cls, downloaders: List['Downloader']) -> pd.DataFrame:
        """Combine info data from multiple Downloader instances."""
        try:
            dfs = []
            for d in downloaders:
                df = d.get_info_data()
                if not df.empty:
                    dfs.append(df)
                else:
                    _logger.warning("No info data for %s", d.ticker)

            if not dfs:
                return pd.DataFrame()

            combined = pd.concat(dfs, ignore_index=True)
            combined = combined.reindex(columns=combined.columns, fill_value=pd.NA)
            return combined

        except Exception as e:
            tickers = [d.ticker for d in downloaders]
            _logger.error(f"combine_info_data failed for {tickers}: {e}", exc_info=True)
            return pd.DataFrame()

    @classmethod
    def stream_download(
        cls,
        tickers: list[str],
        limiter: "RateLimiter",
        out_dir: str = "financial_data",
    ):
        """Stream tickers one by one, saving each to Parquet as soon as ready.

        Yields each successfully downloaded ``Downloader`` instance.

        Note: ``out_dir`` is relative to the caller's working directory, not the
        package root. Pass an absolute path (e.g. ``str(Path.cwd() / "data")``) if
        you need deterministic output placement from notebooks or scripts.
        """
        os.makedirs(out_dir, exist_ok=True)

        for t in tickers:
            limiter.acquire()
            try:
                d = cls.from_ticker(t)

                tables = {
                    "merged_data": d.get_merged_data(),
                    "info": d.get_info_data()
                }

                for name, df in tables.items():
                    try:
                        if df is not None and not df.empty:
                            path = os.path.join(out_dir, f"{t}_{name}.parquet")
                            df.to_parquet(path)
                    except Exception as e:
                        _logger.error(f"[{t}] Parquet write failed for '{name}': {e}")

                _logger.info("[%s] Saved data to %s", t, out_dir)
                yield d

            except Exception as e:
                _logger.error(f"[{t}] Download failed: {e}", exc_info=True)
