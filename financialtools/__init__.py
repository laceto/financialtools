# financialtools public API
#
# Import from here rather than from internal modules so that internal
# refactors (renames, moves) are absorbed at this boundary without
# breaking callers.
#
# Surface:
#   - Core pipeline classes  : Downloader, FundamentalTraderAssistant,
#                              DownloaderWrapper, FundamentalEvaluator
#   - Analysis entry point   : run_topic_analysis
#   - Public helpers         : build_weights, filter_year, normalise_time
#   - Result merging         : merge_results
#   - Threading utility      : RateLimiter
#   - Exceptions             : DownloadError, EvaluationError, SectorNotFoundError

from financialtools.analysis import (
    build_weights,
    filter_year,
    normalise_time,
    run_topic_analysis,
)
from financialtools.exceptions import DownloadError, EvaluationError, SectorNotFoundError
from financialtools.processor import Downloader, FundamentalTraderAssistant
from financialtools.utils import RateLimiter
from financialtools.wrappers import DownloaderWrapper, FundamentalEvaluator, merge_results

__all__ = [
    # analysis helpers
    "build_weights",
    "filter_year",
    "normalise_time",
    "run_topic_analysis",
    # exceptions
    "DownloadError",
    "EvaluationError",
    "SectorNotFoundError",
    # core pipeline classes
    "Downloader",
    "FundamentalTraderAssistant",
    "DownloaderWrapper",
    "FundamentalEvaluator",
    # result helpers
    "merge_results",
    # threading utility
    "RateLimiter",
]
