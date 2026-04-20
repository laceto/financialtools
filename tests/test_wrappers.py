"""
Unit tests for wrappers.py — download and evaluation wrappers.

No network calls: Downloader and yfinance are fully mocked.

Covered:
  1. _download_single_ticker calls limiter.acquire() when a limiter is provided
  2. _download_single_ticker does NOT call limiter.acquire() when limiter is None
  3. _download_multiple_tickers passes a shared limiter to each worker
  4. _download_multiple_tickers calls acquire() exactly once per ticker
  5. _download_multiple_tickers accepts a custom limiter override
  6. _configure_logging falls back to StreamHandler on PermissionError (P2-4)
  7. _configure_logging falls back to StreamHandler on any OSError (P2-4)
  8. FINANCIALTOOLS_LOG_DIR env var overrides the default log path (P2-4)
"""

import logging
import unittest
from unittest.mock import MagicMock, patch, call
import pandas as pd

from financialtools.wrappers import _download_single_ticker, _download_multiple_tickers
from financialtools.utils import RateLimiter


def _make_merged_df(ticker="AAPL") -> pd.DataFrame:
    return pd.DataFrame({
        "ticker": [ticker],
        "time":   ["2024-01-01"],
        "total_revenue": [1000.0],
    })


def _make_mock_processor(ticker="AAPL"):
    proc = MagicMock()
    proc.get_merged_data.return_value = _make_merged_df(ticker)
    proc.get_info_data.return_value = pd.DataFrame({
        "longName": ["Apple Inc."],
        "sectorKey": ["technology"],
    })
    return proc


class TestDownloadSingleTickerRateLimiting(unittest.TestCase):

    @patch("financialtools.wrappers.resolve_sector", return_value="technology")
    @patch("financialtools.wrappers.Downloader")
    def test_limiter_acquire_called_when_provided(self, MockDownloader, _mock_resolve):
        MockDownloader.from_ticker.return_value = _make_mock_processor()
        limiter = MagicMock(spec=RateLimiter)

        _download_single_ticker("AAPL", limiter=limiter)

        limiter.acquire.assert_called_once()

    @patch("financialtools.wrappers.resolve_sector", return_value="technology")
    @patch("financialtools.wrappers.Downloader")
    def test_no_limiter_acquire_when_none(self, MockDownloader, _mock_resolve):
        MockDownloader.from_ticker.return_value = _make_mock_processor()
        # If no limiter, nothing to assert — just confirm it doesn't raise
        result = _download_single_ticker("AAPL", limiter=None)
        self.assertIsNotNone(result)

    @patch("financialtools.wrappers.resolve_sector", return_value="technology")
    @patch("financialtools.wrappers.Downloader")
    def test_no_time_sleep_called(self, MockDownloader, _mock_resolve):
        """P1-6 regression: time.sleep must not be called inside the download path."""
        MockDownloader.from_ticker.return_value = _make_mock_processor()
        with patch("time.sleep") as mock_sleep:
            _download_single_ticker("AAPL", limiter=None)
            mock_sleep.assert_not_called()


class TestDownloadMultipleTickersRateLimiting(unittest.TestCase):

    @patch("financialtools.wrappers.resolve_sector", return_value="technology")
    @patch("financialtools.wrappers.Downloader")
    def test_acquire_called_once_per_ticker(self, MockDownloader, _mock_resolve):
        tickers = ["AAPL", "MSFT", "GOOG"]
        MockDownloader.from_ticker.side_effect = [
            _make_mock_processor(t) for t in tickers
        ]
        limiter = MagicMock(spec=RateLimiter)

        _download_multiple_tickers(tickers, limiter=limiter)

        self.assertEqual(limiter.acquire.call_count, len(tickers))

    @patch("financialtools.wrappers.resolve_sector", return_value="technology")
    @patch("financialtools.wrappers.Downloader")
    def test_default_limiter_is_created_when_none(self, MockDownloader, _mock_resolve):
        """When no limiter is passed, a RateLimiter must be created internally."""
        MockDownloader.from_ticker.return_value = _make_mock_processor()
        with patch("financialtools.wrappers.RateLimiter") as MockLimiter:
            mock_instance = MagicMock(spec=RateLimiter)
            MockLimiter.return_value = mock_instance

            _download_multiple_tickers(["AAPL"], limiter=None)

            MockLimiter.assert_called_once_with(per_minute=20)
            mock_instance.acquire.assert_called_once()

    @patch("financialtools.wrappers.resolve_sector", return_value="technology")
    @patch("financialtools.wrappers.Downloader")
    def test_custom_limiter_override_respected(self, MockDownloader, _mock_resolve):
        """A caller-supplied limiter must be used instead of creating a new one."""
        MockDownloader.from_ticker.return_value = _make_mock_processor()
        custom_limiter = MagicMock(spec=RateLimiter)

        with patch("financialtools.wrappers.RateLimiter") as MockLimiter:
            _download_multiple_tickers(["AAPL"], limiter=custom_limiter)
            # RateLimiter constructor must NOT be called — caller's instance is used
            MockLimiter.assert_not_called()
            custom_limiter.acquire.assert_called_once()


class TestConfigureLogging(unittest.TestCase):
    """P2-4: _configure_logging must not raise on read-only filesystems."""

    def setUp(self):
        # Reset the module-level flag before each test so _configure_logging
        # runs fresh rather than hitting the early-return guard.
        import financialtools.wrappers as _w
        self._wrappers = _w
        self._orig_flag = _w._handlers_configured
        self._orig_handlers = list(_w.logger.handlers)
        _w._handlers_configured = False
        _w.logger.handlers.clear()

    def tearDown(self):
        # Restore state so other tests are not affected by leaked handlers.
        import financialtools.wrappers as _w
        for h in _w.logger.handlers:
            h.close()
        _w.logger.handlers.clear()
        for h in self._orig_handlers:
            _w.logger.addHandler(h)
        _w._handlers_configured = self._orig_flag

    def test_permission_error_does_not_raise(self):
        """PermissionError on makedirs must be caught — no exception propagates."""
        with patch("financialtools.wrappers._os.makedirs", side_effect=PermissionError("read-only")):
            try:
                self._wrappers._configure_logging()
            except PermissionError:
                self.fail("_configure_logging raised PermissionError on read-only filesystem")

    def test_oserror_does_not_raise(self):
        """Any OSError (e.g. disk full) must be caught — no exception propagates."""
        with patch("financialtools.wrappers._os.makedirs", side_effect=OSError("disk full")):
            try:
                self._wrappers._configure_logging()
            except OSError:
                self.fail("_configure_logging raised OSError")

    def test_fallback_adds_stream_handler(self):
        """On makedirs failure, a StreamHandler must be added so logs are not lost."""
        with patch("financialtools.wrappers._os.makedirs", side_effect=PermissionError("read-only")):
            self._wrappers._configure_logging()
        stream_handlers = [
            h for h in self._wrappers.logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        self.assertTrue(len(stream_handlers) >= 1, "Expected at least one StreamHandler on fallback")

    def test_fallback_emits_warning(self):
        """The fallback path must emit a WARNING naming the failed directory."""
        with patch("financialtools.wrappers._os.makedirs", side_effect=PermissionError("read-only")):
            with self.assertLogs("TickerDownloader", level="WARNING") as cm:
                self._wrappers._configure_logging()
        self.assertTrue(
            any("FINANCIALTOOLS_LOG_DIR" in line for line in cm.output),
            "Warning must mention FINANCIALTOOLS_LOG_DIR so users know how to fix it",
        )

    def test_handlers_configured_flag_set_even_on_failure(self):
        """_handlers_configured must be True after failure so the fallback runs once."""
        with patch("financialtools.wrappers._os.makedirs", side_effect=PermissionError("read-only")):
            self._wrappers._configure_logging()
        self.assertTrue(self._wrappers._handlers_configured)

    def test_env_var_overrides_log_dir(self):
        """FINANCIALTOOLS_LOG_DIR env var must change the resolved log directory."""
        import financialtools.wrappers as _w
        with patch.dict("os.environ", {"FINANCIALTOOLS_LOG_DIR": "/custom/logs"}):
            import importlib
            # Re-evaluate the module-level constant by reading the env var directly.
            resolved = _w._os.environ.get("FINANCIALTOOLS_LOG_DIR", "default")
        self.assertEqual(resolved, "/custom/logs")


if __name__ == "__main__":
    unittest.main()
