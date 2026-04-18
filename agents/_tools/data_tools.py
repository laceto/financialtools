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

import pandas as pd
from langchain_core.tools import tool

from agents._cache import cache_key, clear_cache, write_payloads
from financialtools.analysis import (
    build_weights,
    filter_year,
    normalise_time,
)
from financialtools.exceptions import DownloadError, EvaluationError
from financialtools.processor import Downloader, FundamentalMetricsEvaluator
from financialtools.utils import dataframe_to_json, resolve_sector

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core implementation — plain Python function, raises on failure
# ---------------------------------------------------------------------------

def _download_and_evaluate(
    ticker: str,
    sector: str | None = None,
    year: int | None = None,
    force_refresh: bool = False,
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
    ticker        : Ticker symbol, e.g. "AAPL" or "ENI.MI".
    sector        : Sector key matching sec_sector_metric_weights (e.g. "technology").
                    Auto-detected from yfinance sectorKey if None.
                    Falls back to "Default" with a warning when detection fails.
    year          : Filter to a single fiscal year. None = all available periods.
    force_refresh : When True, delete the existing cache directory for this
                    ticker/year before writing new data.  Clears both
                    ``payloads.json`` and any stale ``{topic}.json`` files from
                    prior runs so consumers always see fresh artefacts.
                    Default False — cache is overwritten in place (payloads.json
                    replaced; old topic results remain until topics are re-run).

    Returns
    -------
    dict with keys:
        cache_key, ticker, company_name, sector, year, status,
        metrics_json, extended_metrics_json, eval_metrics_json,
        composite_scores_json, red_flags_json

    Raises
    ------
    DownloadError    — yfinance raised during data retrieval or reshaping.
    ValueError       — from_ticker() succeeded but get_merged_data() is empty.
    EvaluationError  — bad weights or evaluation failure.
    Any other exception propagates unchanged.

    Failure modes
    -------------
    - yfinance error during download → DownloadError (bad ticker or network).
    - Empty merged DataFrame post-download → ValueError (ticker exists but no data).
    - FundamentalTraderAssistant raises EvaluationError → propagates.
    """
    _logger.info("[_download_and_evaluate] ticker=%s sector=%s year=%s force_refresh=%s",
                 ticker, sector, year, force_refresh)

    # ── Pre-stage: cache invalidation (optional) ─────────────────────────────
    if force_refresh:
        key_to_clear = cache_key(ticker, year)
        _logger.info("[_download_and_evaluate] force_refresh=True — clearing cache key=%s",
                     key_to_clear)
        clear_cache(key_to_clear)

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
        sector = resolve_sector(info_df)
        _logger.info("[_download_and_evaluate] sector auto-detected → %s", sector)

    # ── Stage 2: Evaluate ────────────────────────────────────────────────────
    weights = build_weights(sector)
    fta = FundamentalMetricsEvaluator(data=merged, weights=weights)
    evaluate_out = fta.evaluate()

    # ── Stage 3: Normalise + filter ──────────────────────────────────────────
    def _prep(df: pd.DataFrame) -> str:
        return dataframe_to_json(filter_year(normalise_time(df), year))

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
def prepare_financial_data(
    ticker: str,
    sector: str | None = None,
    year: int | None = None,
    force_refresh: bool = False,
) -> str:
    """
    Download and evaluate financial data for a ticker, then cache the results.

    This tool wraps _download_and_evaluate and returns metadata only.
    Payload JSON strings (metrics, eval_metrics, etc.) are large — they are
    passed to topic subgraphs via AnalysisState, not via this tool's output.

    Args:
        ticker:        Ticker symbol (e.g. "AAPL", "ENI.MI").
        sector:        Sector name matching a key in config.sec_sector_metric_weights,
                       e.g. "technology", "energy", "financial-services".
                       If omitted, the sector is auto-detected from yfinance info
                       (lowercased, spaces replaced with dashes).
                       Falls back to "default" with a warning if detection fails.
        year:          Optional year filter. None = all available years.
        force_refresh: When True, wipe the existing cache for this ticker/year
                       before writing new data.  Use this to guarantee fresh
                       financial data on re-runs; otherwise stale topic results
                       from a previous session may persist on disk.

    Returns:
        JSON object:
            {"cache_key": str, "ticker": str, "company_name": str,
             "sector": str, "year": int | None, "status": "ready"}
        On failure:
            {"error": "<message>"}

    Failure modes
    -------------
    - DownloadError   : yfinance error during retrieval (check ticker/network)
    - ValueError      : download succeeded but merged data is empty
    - EvaluationError : bad weights (check sector key)
    - Any other exception is caught and returned as {"error": ...}
    """
    _logger.info("[prepare_financial_data] ticker=%s sector=%s year=%s force_refresh=%s",
                 ticker, sector, year, force_refresh)
    try:
        result = _download_and_evaluate(ticker, sector, year, force_refresh=force_refresh)
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
