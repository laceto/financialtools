"""
agents/_tools/topic_tools.py — Per-topic LLM analysis tools for financial subagents.

Seven tools, one per metric group.  Each tool:
  1. Reads the five JSON payloads from the disk cache (written by prepare_financial_data).
  2. Builds the appropriate LangChain chain using analysis._build_topic_chain().
  3. Invokes the chain with the one-shot fix retry from analysis._invoke_chain().
  4. Writes the Pydantic assessment back to the cache as JSON.
  5. Returns the assessment as a JSON string (or {"error": ...} on failure).

Tool inventory
--------------
run_liquidity_analysis(cache_key)     → LiquidityAssessment JSON
run_solvency_analysis(cache_key)      → SolvencyAssessment JSON
run_profitability_analysis(cache_key) → ProfitabilityAssessment JSON
run_efficiency_analysis(cache_key)    → EfficiencyAssessment JSON
run_cash_flow_analysis(cache_key)     → CashFlowAssessment JSON
run_growth_analysis(cache_key)        → GrowthAssessment JSON
run_red_flags_analysis(cache_key)     → RedFlagsAssessment JSON

Design invariants
-----------------
- Each tool is given to exactly one subagent (its matching specialist).
- Tools never raise — errors are returned as {"error": "..."}.
- The LLM model defaults to "gpt-4.1-nano" and can be overridden at
  module import time via TOPIC_TOOLS_MODEL env variable.
- Pydantic v2 serialisation: .model_dump() (not .dict()).
"""

from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from agents._cache import cache_key as make_cache_key
from agents._cache import read_payloads, write_topic_result
from financialtools.analysis import _build_topic_chain, _invoke_chain

load_dotenv()

_logger = logging.getLogger(__name__)

# Override model at import time via env var (e.g. for testing with a cheaper model).
_DEFAULT_MODEL = os.getenv("TOPIC_TOOLS_MODEL", "gpt-4.1-nano")


def _run_topic(cache_key: str, topic: str) -> str:
    """
    Shared implementation for all seven topic tools.

    Reads payloads from cache, builds chain for `topic`, invokes with retry,
    writes result back to cache, and returns the assessment as JSON.

    Returns {"error": "..."} on any failure.
    """
    _logger.info("[%s] Starting analysis for topic '%s'", cache_key, topic)
    try:
        payloads = read_payloads(cache_key)
    except FileNotFoundError as exc:
        return json.dumps({"error": str(exc)})

    ticker = payloads.get("ticker", cache_key)

    try:
        llm = ChatOpenAI(model=_DEFAULT_MODEL, temperature=0)

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
            _logger.warning("[%s] %s", cache_key, msg)
            return json.dumps({"error": msg})

        result_dict = assessment.model_dump()
        write_topic_result(cache_key, topic, result_dict)

        _logger.info("[%s] '%s' assessment complete.", cache_key, topic)
        return json.dumps(result_dict)

    except Exception as exc:
        _logger.error("[%s] unexpected error in topic '%s'", cache_key, topic, exc_info=True)
        return json.dumps({"error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# Topic tools — one per metric group
# ─────────────────────────────────────────────────────────────────────────────

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


# ─── Convenience list for subagent wiring ─────────────────────────────────────

TOPIC_TOOLS = {
    "liquidity":     run_liquidity_analysis,
    "solvency":      run_solvency_analysis,
    "profitability": run_profitability_analysis,
    "efficiency":    run_efficiency_analysis,
    "cash_flow":     run_cash_flow_analysis,
    "growth":        run_growth_analysis,
    "red_flags":     run_red_flags_analysis,
}
