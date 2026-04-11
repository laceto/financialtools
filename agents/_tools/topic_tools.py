"""
agents/_tools/topic_tools.py — Per-topic LLM analysis tools for financial subagents.

Public API
----------
_analyse_topic(payloads, topic, model) → str
    Core LLM implementation.  Accepts a payloads dict (keys: ticker, metrics,
    extended_metrics, composite_scores, eval_metrics, red_flags) and runs the
    full chain: build → invoke with retry → write topic result to cache.
    Never raises — returns {"error": "..."} on failure.
    Called directly by topic subgraph nodes (data from state, no disk reads).

_run_topic(cache_key, topic) → str
    Disk-cache shim: reads payloads from agents/.cache/{key}/payloads.json,
    then delegates to _analyse_topic.
    Used by the @tool wrappers for backward compatibility and CLI use.

run_*_analysis(cache_key) [@tool × 7]
    LangChain tools — one per metric group.  Thin wrappers around _run_topic.
    Called by @tool wrappers; kept for backward compatibility and testing.

TOPIC_TOOLS : dict[str, StructuredTool]
    Convenience map: topic name → compiled tool.

Design invariants
-----------------
- _analyse_topic is the single implementation of the LLM chain call.
- @tool wrappers are the backward-compatible surface — they always go through
  the disk cache (read_payloads → _analyse_topic).
- Subgraph nodes bypass the @tool wrappers entirely: they call _analyse_topic
  directly with payloads read from AnalysisState.
- Tools never raise — errors are returned as {"error": "..."}.
- The LLM model defaults to "gpt-4.1-nano"; override via TOPIC_TOOLS_MODEL env
  var (affects @tool wrappers) or by passing model= to _analyse_topic directly.
- Pydantic v2 serialisation: .model_dump() (not .dict()).
"""

from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from agents._cache import read_payloads, write_topic_result
from financialtools.analysis import _build_topic_chain, _invoke_chain

load_dotenv()

_logger = logging.getLogger(__name__)

# Override model at import time via env var (e.g. for testing with a cheaper model).
_DEFAULT_MODEL = os.getenv("TOPIC_TOOLS_MODEL", "gpt-4.1-nano")


# ---------------------------------------------------------------------------
# Core implementation — accepts payloads dict, never raises
# ---------------------------------------------------------------------------

def _analyse_topic(payloads: dict, topic: str, model: str = _DEFAULT_MODEL) -> str:
    """
    Run the LLM analysis chain for one topic given a pre-loaded payloads dict.

    This is the single implementation used by both topic subgraph nodes
    (payloads from state) and the @tool wrappers (payloads from disk cache).

    Parameters
    ----------
    payloads : dict with required keys:
                   ticker, metrics, extended_metrics, composite_scores,
                   eval_metrics, red_flags
               Optional key: cache_key (used for logging and cache write).
    topic    : One of the seven topic keys
               ("liquidity", "solvency", "profitability", "efficiency",
                "cash_flow", "growth", "red_flags").
    model    : LLM model name. Defaults to _DEFAULT_MODEL.

    Returns
    -------
    JSON string — the Pydantic assessment as a dict, or {"error": "..."}.
    Never raises.

    Side-effect
    -----------
    On success, writes the result to agents/.cache/{cache_key}/{topic}.json
    when payloads contains "cache_key" (for observability / warm restarts).
    """
    log_key = payloads.get("cache_key", payloads.get("ticker", "unknown"))
    ticker  = payloads.get("ticker", log_key)

    _logger.info("[%s] Starting analysis for topic '%s'", log_key, topic)
    try:
        llm = ChatOpenAI(model=model, temperature=0)
        prompt, parser = _build_topic_chain(topic, llm)

        inputs = {
            "metrics":          payloads["metrics"],
            "extended_metrics": payloads["extended_metrics"],
            "composite_scores": payloads["composite_scores"],
            "eval_metrics":     payloads["eval_metrics"],
            "red_flags":        payloads["red_flags"],
        }

        assessment = _invoke_chain(prompt, parser, llm, inputs, topic, ticker)

        if assessment is None:
            msg = f"LLM chain for topic '{topic}' failed after fix retry — see logs."
            _logger.warning("[%s] %s", log_key, msg)
            return json.dumps({"error": msg})

        result_dict = assessment.model_dump()

        # Write to cache for observability when cache_key is known.
        if "cache_key" in payloads:
            write_topic_result(payloads["cache_key"], topic, result_dict)

        _logger.info("[%s] '%s' assessment complete.", log_key, topic)
        return json.dumps(result_dict)

    except Exception as exc:
        _logger.error("[%s] unexpected error in topic '%s'", log_key, topic, exc_info=True)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Disk-cache shim — used only by @tool wrappers
# ---------------------------------------------------------------------------

def _run_topic(cache_key: str, topic: str) -> str:
    """
    Read payloads from the disk cache then delegate to _analyse_topic.

    Used exclusively by the @tool wrappers below (backward compatibility).
    Topic subgraph nodes call _analyse_topic directly with payloads from state.

    Returns {"error": "..."} on FileNotFoundError or any _analyse_topic failure.
    """
    try:
        payloads = read_payloads(cache_key)
    except FileNotFoundError as exc:
        return json.dumps({"error": str(exc)})
    payloads["cache_key"] = cache_key
    return _analyse_topic(payloads, topic)


# ---------------------------------------------------------------------------
# Topic tools — one per metric group (@tool wrappers, backward compat)
# ---------------------------------------------------------------------------

@tool
def run_liquidity_analysis(cache_key: str) -> str:
    """
    Assess liquidity for the ticker identified by cache_key.

    Analyses CurrentRatio, QuickRatio, CashRatio, WorkingCapitalRatio (scored)
    and the working capital efficiency chain: DSO, DIO, DPO, CCC (extended).

    Args:
        cache_key: Identifier returned by prepare_financial_data.

    Returns:
        JSON with fields: rating ("strong"|"adequate"|"weak"),
        rationale, working_capital_efficiency, concerns.
        Returns {"error": "..."} on failure.
    """
    return _run_topic(cache_key, "liquidity")


@tool
def run_solvency_analysis(cache_key: str) -> str:
    """
    Assess solvency / leverage for the ticker identified by cache_key.

    Analyses DebtToEquity, DebtRatio, EquityRatio, NetDebtToEBITDA,
    InterestCoverage (scored) and DebtGrowth (extended).

    Args:
        cache_key: Identifier returned by prepare_financial_data.

    Returns:
        JSON with fields: rating ("strong"|"adequate"|"weak"),
        rationale, debt_trend, concerns.
        Returns {"error": "..."} on failure.
    """
    return _run_topic(cache_key, "solvency")


@tool
def run_profitability_analysis(cache_key: str) -> str:
    """
    Assess profitability for the ticker identified by cache_key.

    Analyses GrossMargin, OperatingMargin, NetProfitMargin, EBITDAMargin,
    ROA, ROE, ROIC (scored) and Accruals earnings-quality ratio (extended).

    Args:
        cache_key: Identifier returned by prepare_financial_data.

    Returns:
        JSON with fields: rating ("strong"|"adequate"|"weak"),
        rationale, earnings_quality, concerns.
        Returns {"error": "..."} on failure.
    """
    return _run_topic(cache_key, "profitability")


@tool
def run_efficiency_analysis(cache_key: str) -> str:
    """
    Assess operational efficiency for the ticker identified by cache_key.

    Analyses AssetTurnover (scored) and the working capital chain:
    ReceivablesTurnover, DSO, InventoryTurnover, DIO, PayablesTurnover,
    DPO, CCC (extended).

    Args:
        cache_key: Identifier returned by prepare_financial_data.

    Returns:
        JSON with fields: rating ("strong"|"adequate"|"weak"),
        rationale, working_capital_chain, concerns.
        Returns {"error": "..."} on failure.
    """
    return _run_topic(cache_key, "efficiency")


@tool
def run_cash_flow_analysis(cache_key: str) -> str:
    """
    Assess cash flow quality for the ticker identified by cache_key.

    Analyses FCFToRevenue, FCFYield, FCFtoDebt, OCFRatio, FCFMargin,
    CashConversion, CapexRatio (scored) and FCFGrowth, CapexToDepreciation
    (extended).

    Args:
        cache_key: Identifier returned by prepare_financial_data.

    Returns:
        JSON with fields: rating ("strong"|"adequate"|"weak"),
        rationale, capital_allocation, concerns.
        Returns {"error": "..."} on failure.
    """
    return _run_topic(cache_key, "cash_flow")


@tool
def run_growth_analysis(cache_key: str) -> str:
    """
    Assess growth trajectory for the ticker identified by cache_key.

    Analyses RevenueGrowth, NetIncomeGrowth, FCFGrowth (year-over-year)
    and Dilution (share count change) — all extended metrics.

    Args:
        cache_key: Identifier returned by prepare_financial_data.

    Returns:
        JSON with fields: trajectory ("accelerating"|"stable"|"decelerating"|"declining"),
        rationale, dilution_impact, concerns.
        Returns {"error": "..."} on failure.
    """
    return _run_topic(cache_key, "growth")


@tool
def run_red_flags_analysis(cache_key: str) -> str:
    """
    Identify red flags for the ticker identified by cache_key.

    Examines raw_red_flags (negative FCF/OCF, EBITDA >> OCF), threshold flags
    (negative margins, high D/E, negative ROA/ROE), and quality ratios
    (Accruals, DebtGrowth, Dilution, CapexToDepreciation).

    Args:
        cache_key: Identifier returned by prepare_financial_data.

    Returns:
        JSON with fields: severity ("none"|"low"|"moderate"|"high"),
        rationale, cash_flow_flags, threshold_flags, quality_concerns.
        Returns {"error": "..."} on failure.
    """
    return _run_topic(cache_key, "red_flags")


@tool
def run_quantitative_overview_analysis(cache_key: str) -> str:
    """
    Produce a cross-cutting quantitative overview for the ticker identified by cache_key.

    Analyses all five payload types together:
      - composite_scores: score trend and per-dimension profile across time periods
      - eval_metrics:     P/E, P/B, P/FCF, EarningsYield, FCFYield (valuation context)
      - metrics:          24 scored fundamentals (cross-dimensional coherence check)
      - extended_metrics: 14 unscored diagnostics (growth, working capital, quality ratios)
      - red_flags:        cash-flow and threshold flags (surface vs. underlying quality)

    This agent complements the seven topic-specific agents by surfacing patterns
    that span multiple dimensions and cannot be attributed to a single topic.

    Args:
        cache_key: Identifier returned by prepare_financial_data.

    Returns:
        JSON with fields:
          overall_rating ("strong"|"adequate"|"weak"),
          composite_trend ("improving"|"stable"|"deteriorating"),
          composite_trend_rationale, scoring_profile, valuation_context,
          cross_dimensional_signals,
          data_completeness ("complete"|"partial"|"sparse"),
          concerns.
        Returns {"error": "..."} on failure.
    """
    return _run_topic(cache_key, "quantitative_overview")


# ─── Convenience map for external use (tests, CLI) ───────────────────────────

TOPIC_TOOLS = {
    "liquidity":             run_liquidity_analysis,
    "solvency":              run_solvency_analysis,
    "profitability":         run_profitability_analysis,
    "efficiency":            run_efficiency_analysis,
    "cash_flow":             run_cash_flow_analysis,
    "growth":                run_growth_analysis,
    "red_flags":             run_red_flags_analysis,
    "quantitative_overview": run_quantitative_overview_analysis,
}
