# Multi-Agent Team — Implementation Notes

> **Status: implemented.**
> This file was the original design spec for the LangGraph multi-agent workflow.
> The system is now fully built and documented — refer to the live docs below.

## Where to find the docs

| What you need | Where to look |
|---|---|
| Full architecture, module map, state schema, subgraphs, tools, cache, debugging | `agents/AGENTS.md` |
| Data flow and agent pipeline in context of the full library | `architecture.md` |
| Usage examples and quick-start | `README.md` → *Multi-agent workflow* section |
| Node functions and report prompt | `agents/graph_nodes.py` |
| Shared state schema (`AnalysisState`) | `agents/graph_state.py` |
| Graph wiring (parallel fan-out) | `agents/financial_agent.py` |

## Original design decisions — what was kept and what changed

| Spec idea | Final implementation |
|---|---|
| `StateGraph` + subgraphs | ✅ Implemented as described |
| Shared `AnalysisState` TypedDict | ✅ All keys use `Annotated[T, _last]` reducer to avoid `InvalidUpdateError` on parallel fan-in |
| Sequential chaining (`liquidity → solvency → …`) | ❌ Changed to **parallel fan-out** — all 7 subgraphs run concurrently from `prepare_data`, fan into `compile_report` |
| `app.stream(input, stream_mode="values")` for streaming | ✅ Supported — use `agent.stream({"ticker": ...}, stream_mode="values")` |
| Subgraph as node in parent graph | ✅ Each topic subgraph compiled with `StateGraph(AnalysisState).compile()` and added via `workflow.add_node(name, subgraph)` |
