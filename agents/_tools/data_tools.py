"""
agents/_tools/data_tools.py — Manager data-preparation tool.

Public API
----------
_download_and_evaluate(ticker, sector, year) → dict
    Core pipeline: download → evaluate → normalise → write cache.
    Returns a plain Python dict with metadata + all five payload JSON strings.
    Raises on failure — callers handle errors.

prepare_financial_data(ticker, sector, year) → str   [@tool]
    Thin LangChain tool wrapper around _download_and_evaluate.
    Returns a JSON string with metadata only (payloads are large; they are
    passed to topic subgraphs via state, not via tool output).
    Returns {"error": "..."} on any failure — never raises.

Design invariants
-----------------
- _download_and_evaluate is the single implementation of stages 1-4.
- prepare_financial_data exists for LLM-facing and test compatibility only.
- The disk cache (agents/.cache/) is written as an observability side-effect
  inside _download_and_evaluate — it is NOT the primary data channel.
- Payload JSON strings flow from prepare_data_node to topic subgraphs via
  AnalysisState, not via disk reads.
"""

from __future__ import annotations

import json
import logging
import re

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


# ---------------------------------------------------------------------------
# Core implementation — plain Python function, raises on failure
# ---------------------------------------------------------------------------

def _download_and_evaluate(
    ticker: str,
    sector: str | None = None,
    year: int | None = None,
) -> dict:
    """
    Download and evaluate financial data for a ticker.

    Stages
    ------
    1. Download merged financials via Downloader.from_ticker().
    1b. Enrich with company name and sector from yfinance info.
    2. Evaluate with FundamentalTraderAssistant (24 scored + 14 unscored metrics).
    3. Normalise timestamps and filter to the requested year.
    4. Write to disk cache (observability side-effect — NOT the data channel).

    Parameters
    ----------
    ticker : Ticker symbol, e.g. "AAPL" or "ENI.MI".
    sector : Sector key matching sec_sector_metric_weights (e.g. "technology").
             Auto-detected from yfinance sectorKey if None.
             Falls back to "Default" with a warning when detection fails.
    year   : Filter to a single fiscal year. None = all available periods.

    Returns
    -------
    dict with keys:
        cache_key, ticker, company_name, sector, year, status,
        metrics_json, extended_metrics_json, eval_metrics_json,
        composite_scores_json, red_flags_json

    Raises
    ------
    ValueError       — empty download result.
    EvaluationError  — bad weights or evaluation failure.
    Any other exception propagates unchanged.

    Failure modes
    -------------
    - Empty merged DataFrame → ValueError (bad ticker or network).
    - FundamentalTraderAssistant raises EvaluationError → propagates.
    """
    _logger.info("[_download_and_evaluate] ticker=%s sector=%s year=%s",
                 ticker, sector, year)

    # ── Stage 1: Download ────────────────────────────────────────────────────
    d = Downloader.from_ticker(ticker)
    merged = d.get_merged_data()

    if merged.empty:
        raise ValueError(
            f"No financial data returned for ticker '{ticker}'. "
            "Verify the symbol and network connectivity."
        )

    # ── Stage 1b: Enrich from info (company name + optional sector) ──────────
    info_df = d.get_info_data()

    if not info_df.empty and "longName" in info_df.columns:
        company_name = info_df["longName"].str.lower().to_string(index=False).strip()
        _logger.info("[_download_and_evaluate] company_name='%s'", company_name)
    else:
        company_name = ticker.lower()
        _logger.warning("[_download_and_evaluate] longName not found in info; using ticker as name")

    if sector is None:
        if not info_df.empty and "sector" in info_df.columns:
            raw = info_df["sector"].str.lower().to_string(index=False)
            sector = re.sub(r" ", "-", raw.strip())
            _logger.info("[_download_and_evaluate] sector auto-detected → %s", sector)
        else:
            sector = "default"
            _logger.warning("[_download_and_evaluate] sector not found in info; using 'default'")

    # ── Stage 2: Evaluate ────────────────────────────────────────────────────
    weights = _build_weights(sector)
    fta = FundamentalTraderAssistant(data=merged, weights=weights)
    evaluate_out = fta.evaluate()

    # ── Stage 3: Normalise + filter ──────────────────────────────────────────
    def _prep(df: pd.DataFrame) -> str:
        return dataframe_to_json(_filter_year(_normalise_time(df), year))

    metrics_json          = _prep(evaluate_out["metrics"])
    extended_metrics_json = _prep(evaluate_out["extended_metrics"])
    eval_metrics_json     = _prep(evaluate_out["eval_metrics"])
    composite_scores_json = _prep(evaluate_out["composite_scores"])
    red_flags_json        = _prep(evaluate_out["red_flags"])

    # ── Stage 4: Write disk cache (observability side-effect) ────────────────
    key = cache_key(ticker, year)
    write_payloads(key, {
        "ticker":           ticker,
        "company_name":     company_name,
        "sector":           sector,
        "year":             year,
        "metrics":          metrics_json,
        "extended_metrics": extended_metrics_json,
        "composite_scores": composite_scores_json,
        "eval_metrics":     eval_metrics_json,
        "red_flags":        red_flags_json,
    })

    _logger.info("[_download_and_evaluate] cache written → key=%s", key)

    return {
        "cache_key":            key,
        "ticker":               ticker,
        "company_name":         company_name,
        "sector":               sector,
        "year":                 year,
        "metrics_json":         metrics_json,
        "extended_metrics_json": extended_metrics_json,
        "eval_metrics_json":    eval_metrics_json,
        "composite_scores_json": composite_scores_json,
        "red_flags_json":       red_flags_json,
        "status":               "ready",
    }


# ---------------------------------------------------------------------------
# Tool wrapper — backward compat, LLM-facing, and test surface
# ---------------------------------------------------------------------------

@tool
def prepare_financial_data(ticker: str, sector: str | None = None, year: int | None = None) -> str:
    """
    Download and evaluate financial data for a ticker, then cache the results.

    This tool wraps _download_and_evaluate and returns metadata only.
    Payload JSON strings (metrics, eval_metrics, etc.) are large — they are
    passed to topic subgraphs via AnalysisState, not via this tool's output.

    Args:
        ticker: Ticker symbol (e.g. "AAPL", "ENI.MI").
        sector: Sector name matching a key in config.sec_sector_metric_weights,
                e.g. "technology", "energy", "financial-services".
                If omitted, the sector is auto-detected from yfinance info
                (lowercased, spaces replaced with dashes).
                Falls back to "default" with a warning if detection fails.
        year:   Optional year filter. None = all available years.

    Returns:
        JSON object:
            {"cache_key": str, "ticker": str, "company_name": str,
             "sector": str, "year": int | None, "status": "ready"}
        On failure:
            {"error": "<message>"}

    Failure modes
    -------------
    - ValueError      : empty download result (check ticker/network)
    - EvaluationError : bad weights (check sector key)
    - Any other exception is caught and returned as {"error": ...}
    """
    _logger.info("[prepare_financial_data] ticker=%s sector=%s year=%s",
                 ticker, sector, year)
    try:
        result = _download_and_evaluate(ticker, sector, year)
        # Return metadata only — payloads are passed to subgraphs via state.
        return json.dumps({
            "cache_key":    result["cache_key"],
            "ticker":       result["ticker"],
            "company_name": result["company_name"],
            "sector":       result["sector"],
            "year":         result["year"],
            "status":       result["status"],
        })
    except EvaluationError as exc:
        _logger.error("[prepare_financial_data] EvaluationError: %s", exc)
        return json.dumps({"error": f"EvaluationError: {exc}"})
    except Exception as exc:
        _logger.error("[prepare_financial_data] unexpected error", exc_info=True)
        return json.dumps({"error": str(exc)})
