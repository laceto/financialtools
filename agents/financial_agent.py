"""
agents/financial_agent.py — Financial Analysis Manager agent.

Public API
----------
create_financial_manager(model, checkpointer) → compiled Deep Agent
    Returns a runnable Deep Agent that accepts:
        {"messages": [{"role": "user", "content": "<request>"}]}
    and returns a TopicAnalysisResult-equivalent structured report.

Usage
-----
    from agents.financial_agent import create_financial_manager

    agent = create_financial_manager()
    config = {"configurable": {"thread_id": "session-1"}}

    result = agent.invoke(
        {"messages": [{"role": "user", "content":
            "Analyse AAPL for sector Technology, year 2023"}]},
        config=config,
    )

Architecture
------------
Manager (Deep Agent)
├── Tools
│   └── prepare_financial_data   — downloads + evaluates, writes cache
├── Subagents (7)
│   ├── liquidity_analyst        ← run_liquidity_analysis
│   ├── solvency_analyst         ← run_solvency_analysis
│   ├── profitability_analyst    ← run_profitability_analysis
│   ├── efficiency_analyst       ← run_efficiency_analysis
│   ├── cash_flow_analyst        ← run_cash_flow_analysis
│   ├── growth_analyst           ← run_growth_analysis
│   └── red_flags_analyst        ← run_red_flags_analysis
└── Built-in (Deep Agents)
    ├── write_todos               — task planning
    ├── task                      — delegation to subagents
    └── filesystem tools          — ls, read_file, write_file, …

Orchestration flow
------------------
1. Manager receives user request (ticker + sector + optional year).
2. Manager plans via write_todos (7 topic tasks + 1 compile task).
3. Manager calls prepare_financial_data(ticker, sector, year).
   → Downloads yfinance data, evaluates 24+14 metrics, writes cache.
4. Manager delegates each topic to its specialist subagent via `task`:
      task(agent="liquidity_analyst",
           instruction="Run liquidity analysis. cache_key=<key>")
   Each subagent calls its tool, writes result to cache, returns JSON.
5. After all 7 subagents return, manager synthesises findings and
   presents a structured report to the user.

Design invariants
-----------------
- prepare_financial_data runs ONCE — all subagents read the same cache.
- Subagents are stateless — each receives its complete instruction in one call.
- Manager uses thread_id for session continuity (stored in checkpointer).
- All tools return JSON strings; {"error": "..."} on failure.
"""

from __future__ import annotations

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

from agents._subagents import build_topic_subagents
from agents._tools.data_tools import prepare_financial_data

# ─── Manager system prompt ────────────────────────────────────────────────────

_MANAGER_SYSTEM_PROMPT = """You are a financial analysis manager responsible for coordinating
a team of specialist subagents to produce a comprehensive fundamental stock analysis report.

Your workflow for every analysis request:

1. **Plan** — Use write_todos to create 9 tasks:
   - "Prepare financial data"
   - "Liquidity analysis"
   - "Solvency analysis"
   - "Profitability analysis"
   - "Efficiency analysis"
   - "Cash flow analysis"
   - "Growth analysis"
   - "Red flags analysis"
   - "Compile final report"

2. **Prepare data** — Call prepare_financial_data(ticker=..., sector=..., year=...).
   This downloads, evaluates, and caches all financial data.
   If it returns an error, report it immediately and stop.

3. **Delegate analyses** — For each topic, call:
      task(agent="<topic>_analyst",
           instruction="Run your analysis. Use cache_key=<cache_key>. Return the full JSON result.")
   You MUST include the cache_key in every delegation instruction.
   Delegate all 7 topics — do not skip any.

4. **Compile report** — After all subagents return, produce a structured report with:
   - Overall assessment (regime signal, key strengths, key risks)
   - Per-topic summary (rating/trajectory + one-sentence insight)
   - Top 3 concerns worth investor attention

Always present the final report in clear markdown with a section per topic.
Never fabricate data — only use what the tools return.
"""


# ─── Factory ─────────────────────────────────────────────────────────────────

def create_financial_manager(
    model: str = "gpt-4.1-nano",
    checkpointer=None,
) -> object:
    """
    Create and return the Financial Analysis Manager deep agent.

    Args:
        model:        LLM model for both the manager and all subagents.
                      Default: "gpt-4.1-nano".
        checkpointer: LangGraph checkpointer for session persistence.
                      Defaults to MemorySaver() (in-process, non-persistent).
                      Pass a SqliteSaver or PostgresSaver for durable sessions.

    Returns:
        Compiled deep agent (LangGraph Runnable).
        Call .invoke({"messages": [...]}, config={"configurable": {"thread_id": "..."}})

    Example
    -------
        agent = create_financial_manager()
        result = agent.invoke(
            {"messages": [{"role": "user", "content":
                "Analyse MSFT for sector Technology, year 2023"}]},
            config={"configurable": {"thread_id": "user-1"}},
        )
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    subagents = build_topic_subagents(model=model)

    return create_deep_agent(
        name="financial-analysis-manager",
        model=model,
        tools=[prepare_financial_data],
        subagents=subagents,
        system_prompt=_MANAGER_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
