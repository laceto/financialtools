"""
agents/graph_state.py — Shared state schema for the LangGraph financial analysis workflow.

AnalysisState flows through the main graph and all seven topic subgraphs.
Each node returns a partial dict; LangGraph merges it into the running state.

State lifecycle
---------------
1. Caller supplies:        ticker, sector (optional), year (optional), model (optional)
2. prepare_data_node adds: cache_key, company_name, resolved_sector
3. Each topic subgraph adds its result key (e.g. liquidity_result)
4. compile_report_node adds: final_report

Invariant: nodes only write their own keys — they never read back keys they wrote.
"""

from __future__ import annotations

from typing import Annotated, Optional

from typing_extensions import TypedDict


def _last(a, b):
    """
    Reducer: last writer wins.

    Required for all keys in a parallel fan-out graph.  When 7 topic
    subgraphs complete simultaneously and fan into compile_report, LangGraph
    merges their state dicts.  Without a reducer it raises InvalidUpdateError
    because the same key (e.g. 'ticker') arrives from multiple branches.
    This reducer silently takes the latest value — safe because scalar keys
    are written exactly once (by prepare_data_node) and topic subgraphs only
    propagate them unchanged.
    """
    return b


class AnalysisState(TypedDict, total=False):
    # ── Caller-supplied inputs ─────────────────────────────────────────────
    ticker: Annotated[str,           _last]   # required
    sector: Annotated[Optional[str], _last]   # None → auto-detected from yfinance sectorKey
    year:   Annotated[Optional[int], _last]   # None → all available years
    model:  Annotated[str,           _last]   # LLM model name; defaults to "gpt-4.1-nano"

    # ── Set by prepare_data_node ───────────────────────────────────────────
    cache_key:       Annotated[str, _last]    # e.g. "AAPL_2023" or "AAPL_all"
    company_name:    Annotated[str, _last]    # lowercased longName, e.g. "apple inc."
    resolved_sector: Annotated[str, _last]    # final sector used

    # ── Set by topic subgraphs (one key per topic) ─────────────────────────
    liquidity_result:     Annotated[Optional[dict], _last]
    solvency_result:      Annotated[Optional[dict], _last]
    profitability_result: Annotated[Optional[dict], _last]
    efficiency_result:    Annotated[Optional[dict], _last]
    cash_flow_result:     Annotated[Optional[dict], _last]
    growth_result:        Annotated[Optional[dict], _last]
    red_flags_result:     Annotated[Optional[dict], _last]

    # ── Set by compile_report_node ─────────────────────────────────────────
    final_report: Annotated[str, _last]       # structured markdown report
