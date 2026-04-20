# financialtools public API
#
# Import from here rather than from internal modules so that internal
# refactors (renames, moves) are absorbed at this boundary without
# breaking callers.
#
# Surface:
#   - Core pipeline classes  : Downloader, FundamentalMetricsEvaluator,
#                              DownloaderWrapper, FundamentalEvaluator
#   - Analysis entry point   : run_topic_analysis
#   - Public helpers         : build_weights, list_sectors, filter_year, normalise_time
#   - Chain helpers          : build_topic_chain, invoke_chain
#   - Result merging         : merge_results, export_financial_results, read_financial_results,
#                              empty_result (empty_evaluate_result is a backward-compat alias)
#   - Threading utility      : RateLimiter
#   - Exceptions             : DownloadError, EvaluationError, SectorNotFoundError
#   - Deprecated             : FundamentalTraderAssistant (use FundamentalMetricsEvaluator)

from financialtools.analysis import (
    build_topic_chain,
    build_weights,
    filter_year,
    invoke_chain,
    list_sectors,
    normalise_time,
    run_topic_analysis,
)
from financialtools.exceptions import DownloadError, EvaluationError, SectorNotFoundError
from financialtools.processor import (
    Downloader,
    FundamentalMetricsEvaluator,
    FundamentalTraderAssistant,  # deprecated alias — use FundamentalMetricsEvaluator
)
from financialtools.evaluator import empty_result
empty_evaluate_result = empty_result  # backward-compat alias — prefer empty_result
from financialtools.utils import RateLimiter, resolve_sector
from financialtools.wrappers import (
    DownloaderWrapper,
    FundamentalEvaluator,
    export_financial_results,
    merge_results,
    read_financial_results,
)

__all__ = [
    # analysis helpers
    "build_topic_chain",
    "build_weights",
    "filter_year",
    "invoke_chain",
    "list_sectors",
    "normalise_time",
    "run_topic_analysis",
    # exceptions
    "DownloadError",
    "EvaluationError",
    "SectorNotFoundError",
    # core pipeline classes
    "Downloader",
    "FundamentalMetricsEvaluator",
    "FundamentalTraderAssistant",  # deprecated alias
    "DownloaderWrapper",
    "FundamentalEvaluator",
    # result helpers
    "merge_results",
    "export_financial_results",
    "read_financial_results",
    "empty_result",
    "empty_evaluate_result",  # backward-compat alias for empty_result
    # threading utility
    "RateLimiter",
    # data utilities
    "resolve_sector",
]
