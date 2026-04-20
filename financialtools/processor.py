"""processor.py — backward-compatible re-export shim.

The implementation has been split into two focused modules:
  - financialtools.downloader  : yfinance data acquisition (Downloader)
  - financialtools.evaluator   : metrics compute & scoring (FundamentalMetricsEvaluator)

All public names remain importable from this module so existing callers are
unaffected. New code should import directly from downloader or evaluator.

Migration note
--------------
``_empty_result``, ``_EMPTY_RESULT_KEYS``, and ``_REQUIRED_METRIC_COLS`` are no
longer re-exported from this shim — they were private implementation details and
should never have been part of the public surface.  Use ``empty_result()`` from
``financialtools.evaluator`` (or ``financialtools`` directly) instead.
"""
# noqa: F401 — all names are re-exported for backward compatibility
from financialtools.downloader import Downloader, RateLimiter
from financialtools.evaluator import (
    FundamentalMetricsEvaluator,
    FundamentalTraderAssistant,
    SCORED_METRICS,
)

__all__ = [
    "Downloader",
    "RateLimiter",
    "FundamentalMetricsEvaluator",
    "FundamentalTraderAssistant",
    "SCORED_METRICS",
]
