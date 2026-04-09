"""
agents/financial_agent.py — Financial Analysis Manager graph.

Public API
----------
create_financial_manager(model, checkpointer) → compiled LangGraph Runnable

    Returns a StateGraph-based workflow that accepts:
        {"ticker": str, "sector": str | None, "year": int | None, "model": str}
    and returns a fully populated AnalysisState, including final_report.

Usage
-----
    from agents.financial_agent import create_financial_manager

    agent  = create_financial_manager()
    config = {"configurable": {"thread_id": "session-1"}}

    result = agent.invoke(
        {"ticker": "AAPL", "year": 2023},
        config=config,
    )
    print(result["final_report"])

Architecture
------------
                    ┌─────────────────────┐
    START ─────────►│   prepare_data      │  downloads + evaluates, writes cache
                    └────────┬────────────┘
           ┌─────────────────┼──── … ──────────────────────┐
           ▼                 ▼                              ▼
    ┌─────────────┐  ┌─────────────┐              ┌───────────────┐
    │  liquidity  │  │  solvency   │  …  (×7)     │  red_flags    │
    │  subgraph   │  │  subgraph   │              │  subgraph     │
    └──────┬──────┘  └──────┬──────┘              └───────┬───────┘
           └─────────────────┴──── … ──────────────────────┘
                                    │ (all must complete)
                                    ▼
                    ┌─────────────────────┐
                    │   compile_report    │  LLM synthesis → final_report
                    └────────┬────────────┘
                             ▼
                            END

Parallel execution
------------------
All seven topic subgraphs fan out from prepare_data and fan in to compile_report.
LangGraph executes them concurrently and waits for all before compile_report runs.

Streaming
---------
Use agent.stream(input, stream_mode="values") to observe intermediate state
updates from each subgraph as they complete.

Design invariants
-----------------
- prepare_data_node is the only node that calls the data download tool.
- Subgraphs are stateless — they only need cache_key from state.
- compile_report_node is the only LLM call that synthesises the full picture.
- Thread-level persistence via checkpointer (MemorySaver by default).
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agents._subagents import TOPIC_NAMES, build_topic_subgraphs
from agents.graph_nodes import compile_report_node, prepare_data_node
from agents.graph_state import AnalysisState


def create_financial_manager(
    model: str = "gpt-4.1-nano",
    checkpointer=None,
) -> object:
    """
    Build and compile the Financial Analysis Manager StateGraph.

    Parameters
    ----------
    model : str
        LLM model name used by both compile_report_node and all topic tools.
        Injected into state so nodes can read it without a closure.
        Default: "gpt-4.1-nano".
    checkpointer :
        LangGraph checkpointer for session persistence.
        Defaults to MemorySaver() (in-process, non-persistent).
        Pass SqliteSaver or PostgresSaver for durable sessions.

    Returns
    -------
    Compiled LangGraph Runnable (CompiledStateGraph).
    Invoke with: agent.invoke({"ticker": ..., "year": ...}, config={...})
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    # ── Node: inject model into state so nodes can read it ──────────────────
    def _set_model(state: AnalysisState) -> dict:
        return {"model": model}

    # ── Build subgraphs ──────────────────────────────────────────────────────
    topic_subgraphs = build_topic_subgraphs()

    # ── Wire the main graph ──────────────────────────────────────────────────
    workflow = StateGraph(AnalysisState)

    workflow.add_node("set_model",      _set_model)
    workflow.add_node("prepare_data",   prepare_data_node)
    workflow.add_node("compile_report", compile_report_node)

    for topic, subgraph in topic_subgraphs.items():
        workflow.add_node(f"{topic}_analyst", subgraph)

    # START → set_model → prepare_data
    workflow.add_edge(START,        "set_model")
    workflow.add_edge("set_model",  "prepare_data")

    # prepare_data → all 7 topic subgraphs (parallel fan-out)
    for topic in TOPIC_NAMES:
        workflow.add_edge("prepare_data", f"{topic}_analyst")

    # all 7 topic subgraphs → compile_report (fan-in; LangGraph waits for all)
    for topic in TOPIC_NAMES:
        workflow.add_edge(f"{topic}_analyst", "compile_report")

    # compile_report → END
    workflow.add_edge("compile_report", END)

    return workflow.compile(checkpointer=checkpointer)
