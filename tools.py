"""
tools.py — LangChain tool wrapper for the financialtools package.

Exposes one @tool function that a LangChain / LangGraph agent can call
to run the full LLM regime report for a ticker.

Tool inventory
--------------
get_stock_regime_report — full LLM regime assessment (StockRegimeAssessment)

Design invariants
-----------------
- Every tool returns a JSON string (never raises to the agent).
- Errors are returned as {"error": "<message>"} so the agent can reason about
  failures without a traceback interrupting the chain.
- base_dir is deployment config, not an agent decision.
  It is baked into the tool at bootstrap time via make_tools(), never
  exposed as a tool parameter the LLM can set.
- Pydantic v2 serialisation uses `.model_dump()` (not `.dict()` or `.json()`).

Usage
-----
    from tools import make_tools

    tools = make_tools(base_dir="/path/to/my/financial_data")
    agent = create_agent(model=llm, tools=tools, ...)
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from chains import get_stock_evaluation_report
from financialtools.exceptions import SectorNotFoundError

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> str:
    """Serialise an error message into the standard tool error envelope."""
    return json.dumps({"error": msg})


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_tools(
    base_dir: str = "financial_data",
) -> list:
    """
    Create the agent tool with base_dir baked in.

    Call this at agent bootstrap time — not at import time — so the path
    can be set by the external consumer without monkey-patching globals.

    Args:
        base_dir: Directory containing the evaluation output files
                  (metrics.xlsx, composite_scores.xlsx, red_flags.xlsx,
                  raw_red_flags.xlsx, eval_metrics.xlsx).
                  Defaults to "financial_data" (relative to CWD).

    Returns:
        List of LangChain @tool objects ready to pass to create_agent().
    """

    @tool
    def get_stock_regime_report(ticker: str, sector: str, year: int | None = None) -> str:
        """
        Run the full LLM fundamental regime assessment for a ticker.

        Calls the complete chains.py pipeline: reads Excel results,
        sends data to gpt-4.1-nano, and returns a structured assessment.

        Args:
            ticker: Ticker symbol (e.g. "AAPL", "ENI.MI").
            sector: Sector name (e.g. "Technology", "Energy", "Finance").
            year:   Optional year to focus the assessment on.

        Returns:
            JSON object with keys:
                regime            — "bull" or "bear"
                evaluation        — "overvalued", "undervalued", or "fair"
                regime_rationale  — LLM explanation of the bull/bear classification
                market_comparison — LLM comparison against sector peers
            Returns {"error": "..."} on any failure.
        """
        try:
            assessment = get_stock_evaluation_report(
                ticker,
                sector=sector,
                year=year,
                base_dir=base_dir,
            )
            return json.dumps(assessment.model_dump())
        except SectorNotFoundError as exc:
            return _err(f"Sector not found for {ticker}: {exc}")
        except FileNotFoundError as exc:
            return _err(f"Financial data files not found — run the pipeline first. Detail: {exc}")
        except Exception as exc:
            _logger.error("get_stock_regime_report failed for %s", ticker, exc_info=True)
            return _err(str(exc))

    return [get_stock_regime_report]


# ---------------------------------------------------------------------------
# Convenience export — in-repo / default usage
# ---------------------------------------------------------------------------

TOOLS = make_tools()
