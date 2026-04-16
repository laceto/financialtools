# financialtools public API
#
# Import from here rather than from internal modules so that internal
# refactors (renames, moves) are absorbed at this boundary without
# breaking callers.

from financialtools.analysis import (
    build_weights,
    filter_year,
    normalise_time,
    run_topic_analysis,
)
from financialtools.exceptions import DownloadError, EvaluationError, SectorNotFoundError
from financialtools.processor import Downloader, FundamentalTraderAssistant
from financialtools.wrappers import DownloaderWrapper, FundamentalEvaluator

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
    # core classes
    "Downloader",
    "FundamentalTraderAssistant",
    "DownloaderWrapper",
    "FundamentalEvaluator",
]
