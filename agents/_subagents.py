"""
agents/_subagents.py — Topic subgraph registry for the financial analysis workflow.

Exports
-------
TOPIC_NAMES          : ordered list of the seven topic keys
build_topic_subgraphs() → dict[str, CompiledStateGraph]

Each value is a compiled single-node StateGraph that:
  1. Reads cache_key from AnalysisState.
  2. Calls the matching topic tool (run_*_analysis).
  3. Writes {topic}_result back to state.

Ordering
--------
TOPIC_NAMES is the authoritative execution order used when wiring the main graph.
All seven run in parallel (fan-out from prepare_data → all topics → compile_report).
"""

from __future__ import annotations

from agents.graph_nodes import create_topic_subgraph

# Authoritative topic order — used for graph wiring and report ordering.
TOPIC_NAMES: list[str] = [
    "liquidity",
    "solvency",
    "profitability",
    "efficiency",
    "cash_flow",
    "growth",
    "red_flags",
    "quantitative_overview",
]


def build_topic_subgraphs() -> dict[str, object]:
    """
    Build and compile one StateGraph per topic.

    Returns
    -------
    dict mapping topic name → compiled StateGraph (LangGraph CompiledStateGraph).
    Call .invoke(state) or use as a node in the parent graph.
    """
    return {topic: create_topic_subgraph(topic) for topic in TOPIC_NAMES}
