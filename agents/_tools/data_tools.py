"""
agents/_tools/data_tools.py — Manager data-preparation tool.

Tool
----
prepare_financial_data(ticker, sector, year)
    Downloads yfinance data, runs FundamentalTraderAssistant.evaluate(), and
    writes the five normalised JSON payloads to the disk cache.

    Returns a JSON object with {cache_key, ticker, sector, year, status}.
    Returns {"error": "..."} on any failure — never raises.

Design invariants
-----------------
- This tool is only given to the manager agent, NOT to subagents.
- Download + evaluate happens exactly once per request.
- The cache key returned here is passed to subagents as part of their instruction.
"""

from __future__ import annotations

import json
import logging

import pandas as pd
from langchain_core.tools import tool

from agents._cache import cache_key, write_payloads
from financialtools.analysis import (
    _build_weights,
    _filter_year,
    _normalise_time,
)
from financialtools.exceptions import EvaluationError
from financialtools.processor import Downloader, FundamentalTraderAssistant
from financialtools.utils import dataframe_to_json

_logger = logging.getLogger(__name__)


@tool
def prepare_financial_data(ticker: str, sector: str, year: int | None = None) -> str:
    """
    Download and evaluate financial data for a ticker, then cache the results.

    This must be called before delegating to any topic subagent.
    The returned cache_key is the identifier that all topic subagents need.

    Args:
        ticker: Ticker symbol (e.g. "AAPL", "ENI.MI").
        sector: Sector name matching a key in config.sector_metric_weights,
                e.g. "Technology", "Energy", "Finance".
                Falls back to "Default" with a warning if not found.
        year:   Optional year filter.  When provided, only data for that year
                is sent to the LLM chains.  None sends all available years.

    Returns:
        JSON object:
            {"cache_key": str, "ticker": str, "sector": str,
             "year": int | None, "status": "ready"}
        On failure:
            {"error": "<message>"}

    Failure modes
    -------------
    - EvaluationError  : empty download result or bad weights (check ticker/sector)
    - Any other exception is caught and returned as {"error": ...}
    """
    _logger.info("[prepare_financial_data] ticker=%s sector=%s year=%s", ticker, sector, year)

    try:
        # ── Stage 1: Download ────────────────────────────────────────────────
        d = Downloader.from_ticker(ticker)
        merged = d.get_merged_data()

        if merged.empty:
            return json.dumps({"error": f"No financial data returned for ticker '{ticker}'. "
                                         "Verify the symbol and network connectivity."})

        # ── Stage 2: Evaluate ────────────────────────────────────────────────
        weights = _build_weights(sector)
        fta = FundamentalTraderAssistant(data=merged, weights=weights)
        evaluate_out = fta.evaluate()

        # ── Stage 3: Normalise + filter ──────────────────────────────────────
        def _prep(df: pd.DataFrame) -> str:
            return dataframe_to_json(_filter_year(_normalise_time(df), year))

        metrics_json          = _prep(evaluate_out["metrics"])
        extended_metrics_json = _prep(evaluate_out["extended_metrics"])
        eval_metrics_json     = _prep(evaluate_out["eval_metrics"])
        composite_scores_json = _prep(evaluate_out["composite_scores"])
        red_flags_json        = _prep(evaluate_out["red_flags"])

        # ── Stage 4: Write cache ─────────────────────────────────────────────
        key = cache_key(ticker, year)
        write_payloads(key, {
            "ticker":           ticker,
            "sector":           sector,
            "year":             year,
            "metrics":          metrics_json,
            "extended_metrics": extended_metrics_json,
            "composite_scores": composite_scores_json,
            "eval_metrics":     eval_metrics_json,
            "red_flags":        red_flags_json,
        })

        _logger.info("[prepare_financial_data] cache written → key=%s", key)
        return json.dumps({
            "cache_key": key,
            "ticker":    ticker,
            "sector":    sector,
            "year":      year,
            "status":    "ready",
        })

    except EvaluationError as exc:
        _logger.error("[prepare_financial_data] EvaluationError: %s", exc)
        return json.dumps({"error": f"EvaluationError: {exc}"})
    except Exception as exc:
        _logger.error("[prepare_financial_data] unexpected error", exc_info=True)
        return json.dumps({"error": str(exc)})
