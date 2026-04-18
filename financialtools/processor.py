"""processor.py — backward-compatible re-export shim.

The implementation has been split into two focused modules:
  - financialtools.downloader  : yfinance data acquisition (Downloader)
  - financialtools.evaluator   : metrics compute & scoring (FundamentalMetricsEvaluator)

All public names remain importable from this module so existing callers are
unaffected. New code should import directly from downloader or evaluator.
"""
# noqa: F401 — all names are re-exported for backward compatibility
from financialtools.downloader import Downloader, RateLimiter
from financialtools.evaluator import (
    FundamentalMetricsEvaluator,
    FundamentalTraderAssistant,
    _empty_result,
    _EMPTY_RESULT_KEYS,
    _REQUIRED_METRIC_COLS,
    SCORED_METRICS,
)

__all__ = [
    "Downloader",
    "RateLimiter",
    "FundamentalMetricsEvaluator",
    "FundamentalTraderAssistant",
    "_empty_result",
    "_EMPTY_RESULT_KEYS",
    "_REQUIRED_METRIC_COLS",
    "SCORED_METRICS",
]
