"""
exceptions.py — Domain exceptions for the financialtools package.

Raising these instead of bare ValueError / RuntimeError gives callers the ability
to handle specific failure modes selectively and makes error contracts explicit.

Hierarchy:
    FinancialToolsError (base)
    ├── DownloadError      — yfinance fetch or data-reshape failure
    ├── EvaluationError    — metric computation or scoring failure
    └── SectorNotFoundError — sector or weight lookup failure
        (also a ValueError so existing `except ValueError` blocks still catch it)
"""


class FinancialToolsError(Exception):
    """Base class for all financialtools domain exceptions."""


class DownloadError(FinancialToolsError):
    """
    Raised when a ticker download or data-reshape step fails unrecoverably.

    Typical sites: Downloader.from_ticker(), DownloaderWrapper.download_data()
    """


class EvaluationError(FinancialToolsError):
    """
    Raised when metric computation, scoring, or evaluate() cannot proceed.

    Typical sites: FundamentalTraderAssistant.__init__(), evaluate()
    """


class SectorNotFoundError(FinancialToolsError, ValueError):
    """
    Raised when a sector or its weights cannot be found.

    Inherits from ValueError so existing `except ValueError` catch-sites
    continue to work without modification.

    Typical sites: get_sector_for_ticker(), get_market_metrics()
    """
