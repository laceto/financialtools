"""
agents — Financial Analysis Manager workflow.

Public API
----------
create_financial_manager(model, checkpointer) → compiled LangGraph StateGraph

Usage
-----
    from agents import create_financial_manager

    agent  = create_financial_manager()
    config = {"configurable": {"thread_id": "session-1"}}

    result = agent.invoke(
        {"ticker": "AAPL", "year": 2023},
        config=config,
    )
    print(result["final_report"])

    # Streaming intermediate state updates:
    for chunk in agent.stream({"ticker": "AAPL"}, config=config, stream_mode="values"):
        print(chunk)
"""

from agents.financial_agent import create_financial_manager

__all__ = ["create_financial_manager"]
