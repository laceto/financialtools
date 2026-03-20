"""
agents — Financial Analysis Manager and topic subagents.

Public API
----------
create_financial_manager(model, checkpointer) → Deep Agent

Usage
-----
    from agents import create_financial_manager

    agent = create_financial_manager()
    config = {"configurable": {"thread_id": "session-1"}}

    result = agent.invoke(
        {"messages": [{"role": "user", "content":
            "Analyse AAPL for sector Technology, year 2023"}]},
        config=config,
    )
    print(result["messages"][-1].content)
"""

from agents.financial_agent import create_financial_manager

__all__ = ["create_financial_manager"]
