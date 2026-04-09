# Financial Analysis Agent System

> **Module:** `agents/`
> **Entry point:** `from agents import create_financial_manager`

---

## Overview

The `agents/` package implements a **manager + 7 specialist subgraph** architecture built on **LangGraph's native `StateGraph`**.

A single `AnalysisState` flows through the main graph. After a data preparation node writes the cache, seven topic subgraphs execute **in parallel**, each appending its result to state. A final compile node synthesises all results into a structured markdown report.

```
START ──► prepare_data ──┬──► liquidity_analyst  ──┐
                         ├──► solvency_analyst   ──┤
                         ├──► profitability_analyst─┤
                         ├──► efficiency_analyst ──┤  (parallel)
                         ├──► cash_flow_analyst  ──┤
                         ├──► growth_analyst     ──┤
                         └──► red_flags_analyst  ──┴──► compile_report ──► END
```

---

## Module Map

| File | Responsibility |
|---|---|
| `__init__.py` | Re-exports `create_financial_manager` as the public API |
| `financial_agent.py` | Main `StateGraph` factory (`create_financial_manager`) |
| `graph_state.py` | `AnalysisState` TypedDict — shared state schema |
| `graph_nodes.py` | `prepare_data_node`, `create_topic_subgraph(topic)`, `compile_report_node` |
| `_subagents.py` | `TOPIC_NAMES` list + `build_topic_subgraphs()` — compiles 7 topic subgraphs |
| `_tools/data_tools.py` | `prepare_financial_data` LangChain tool (called by `prepare_data_node`) |
| `_tools/topic_tools.py` | Seven `run_*_analysis` tools + `TOPIC_TOOLS` map (called by topic subgraphs) |
| `_cache.py` | Disk-based payload cache — `cache_key`, `write_payloads`, `read_payloads`, `write_topic_result`, `read_topic_result` |

---

## Orchestration Flow

```
1. Caller invokes: agent.invoke({"ticker": "AAPL", "year": 2023}, config=...)

2. set_model node     → injects model name into state

3. prepare_data node  → calls prepare_financial_data(ticker, sector, year)
   │   → Downloader.from_ticker("AAPL").get_merged_data()
   │   → FundamentalTraderAssistant.evaluate()  [24 scored + 14 unscored metrics]
   │   → normalise_time + filter_year
   │   → writes agents/.cache/AAPL_2023/payloads.json
   │   → state ← {cache_key, company_name, resolved_sector}

4. 7 topic subgraphs run in parallel, each:
   │   → reads state["cache_key"]
   │   → calls run_{topic}_analysis(cache_key=...)
   │   → invokes LangChain topic chain (with one-shot fix retry)
   │   → writes agents/.cache/AAPL_2023/{topic}.json
   │   → state ← {topic}_result: {...}

5. compile_report node (runs after all 7 complete)
   │   → LLM call with all 7 topic results
   │   → state ← {final_report: "## Overall Assessment ..."}

6. result["final_report"] is the structured markdown report
```

---

## Public API

**Source:** `agents/financial_agent.py`

### Factory

```python
create_financial_manager(
    model: str = "gpt-4.1-nano",
    checkpointer = None,          # defaults to MemorySaver()
) -> CompiledStateGraph
```

### Usage

```python
from agents import create_financial_manager

agent  = create_financial_manager()
config = {"configurable": {"thread_id": "session-1"}}

# Blocking invoke
result = agent.invoke(
    {"ticker": "AAPL", "year": 2023},
    config=config,
)
print(result["final_report"])

# Streaming intermediate updates
for chunk in agent.stream({"ticker": "AAPL"}, config=config, stream_mode="values"):
    print(chunk)
```

**Input keys:**

| Key | Type | Required | Description |
|---|---|---|---|
| `ticker` | `str` | Yes | Ticker symbol, e.g. `"AAPL"` |
| `sector` | `str \| None` | No | yfinance sectorKey (e.g. `"technology"`). Auto-detected if omitted. |
| `year` | `int \| None` | No | Filter to a single year. None = all available periods. |
| `model` | `str` | No | Override LLM model. Defaults to `"gpt-4.1-nano"`. |

---

## State Schema

**Source:** `agents/graph_state.py`

```python
class AnalysisState(TypedDict, total=False):
    # Inputs
    ticker: str
    sector: str | None
    year:   int | None
    model:  str
    # After prepare_data
    cache_key:       str
    company_name:    str      # lowercased longName, e.g. "apple inc."
    resolved_sector: str      # final sector used (auto-detected or caller-supplied)
    # Topic results
    liquidity_result:     dict | None
    solvency_result:      dict | None
    profitability_result: dict | None
    efficiency_result:    dict | None
    cash_flow_result:     dict | None
    growth_result:        dict | None
    red_flags_result:     dict | None
    # Final output
    final_report: str
```

---

## Subgraphs

**Source:** `agents/_subagents.py`, `agents/graph_nodes.py`

Each topic subgraph is a compiled `StateGraph(AnalysisState)` with a single node:

```
START → run_analysis → END
```

`run_analysis` reads `state["cache_key"]`, calls `TOPIC_TOOLS[topic].invoke(...)`, and writes `state["{topic}_result"]`.

| Subgraph node | Tool called | State key written |
|---|---|---|
| `liquidity_analyst` | `run_liquidity_analysis` | `liquidity_result` |
| `solvency_analyst` | `run_solvency_analysis` | `solvency_result` |
| `profitability_analyst` | `run_profitability_analysis` | `profitability_result` |
| `efficiency_analyst` | `run_efficiency_analysis` | `efficiency_result` |
| `cash_flow_analyst` | `run_cash_flow_analysis` | `cash_flow_result` |
| `growth_analyst` | `run_growth_analysis` | `growth_result` |
| `red_flags_analyst` | `run_red_flags_analysis` | `red_flags_result` |

---

## Tools

### `prepare_financial_data`

**Source:** `agents/_tools/data_tools.py` — called directly by `prepare_data_node` (not via LLM).

| Stage | Action |
|---|---|
| 1. Download | `Downloader.from_ticker(ticker).get_merged_data()` |
| 1b. Enrich | `longName` → `company_name`; `sector` auto-detected from `sectorKey` if not supplied |
| 2. Evaluate | `FundamentalTraderAssistant.evaluate()` — 24 scored + 14 unscored metrics |
| 3. Normalise | `_normalise_time()` + `_filter_year()` per DataFrame |
| 4. Cache | `write_payloads(cache_key, {...})` → `agents/.cache/{KEY}/payloads.json` |

Returns JSON: `{"cache_key", "ticker", "company_name", "sector", "year", "status": "ready"}`.

### Topic Tools — `run_*_analysis`

**Source:** `agents/_tools/topic_tools.py` — called by subgraph `run_analysis` nodes.

All share `_run_topic(cache_key, topic)`:
```
read_payloads(cache_key) → _build_topic_chain(topic, llm) → _invoke_chain(...) → write_topic_result(...)
```

| Tool | Key return fields |
|---|---|
| `run_liquidity_analysis` | `rating`, `rationale`, `working_capital_efficiency`, `concerns` |
| `run_solvency_analysis` | `rating`, `rationale`, `debt_trend`, `concerns` |
| `run_profitability_analysis` | `rating`, `rationale`, `earnings_quality`, `concerns` |
| `run_efficiency_analysis` | `rating`, `rationale`, `working_capital_chain`, `concerns` |
| `run_cash_flow_analysis` | `rating`, `rationale`, `capital_allocation`, `concerns` |
| `run_growth_analysis` | `trajectory`, `rationale`, `dilution_impact`, `concerns` |
| `run_red_flags_analysis` | `severity`, `rationale`, `cash_flow_flags`, `threshold_flags`, `quality_concerns` |

All tools return `{"error": "..."}` on failure — never raise.

---

## Cache

**Source:** `agents/_cache.py`

```
agents/.cache/
└── {TICKER}_{YEAR}/
    ├── payloads.json        ← written by prepare_financial_data
    ├── liquidity.json       ← written by run_liquidity_analysis
    ├── solvency.json
    ├── profitability.json
    ├── efficiency.json
    ├── cash_flow.json
    ├── growth.json
    └── red_flags.json
```

Cache is **not auto-invalidated**. Delete `agents/.cache/{KEY}/` to force a fresh run.

---

## Environment Variables

| Variable | Default | Effect |
|---|---|---|
| `OPENAI_API_KEY` | _(required)_ | OpenAI key for all LLM calls |
| `TOPIC_TOOLS_MODEL` | `"gpt-4.1-nano"` | Override LLM model for all seven topic tools at import time |

---

## Tests

**Source:** `tests/test_financial_agent.py`

| Test class | What it covers |
|---|---|
| `TestCacheUtils` | `cache_key` normalisation; write/read roundtrips; `FileNotFoundError` on missing key |
| `TestPrepareFinancialDataTool` | Empty download → error JSON; `EvaluationError` → error JSON; happy path → `cache_key` + `status: ready`; sector auto-detect; fallback to `"Default"` |
| `TestTopicTools` | All 7 topics in `TOPIC_TOOLS`; missing cache key → error JSON |
| `TestSubagents` | 7 subgraphs built; each is a compiled StateGraph |
| `TestManagerAgent` | `create_financial_manager()` constructs without raising; custom model accepted; result has `final_report` key |

```bash
python -m unittest tests/test_financial_agent.py
```

---

## Debugging Guide

| Symptom | Where to look |
|---|---|
| `ValueError: [prepare_data_node] No financial data...` | Verify ticker symbol and network. Check `logs/error.log`. |
| `ValueError: [prepare_data_node] EvaluationError: ...` | Ticker or sector invalid. Check error message for exact cause. |
| Topic subgraph result is `{"error": "No cached payloads..."}` | `prepare_data` node did not complete or `cache_key` not in state. Check graph wiring. |
| Topic result is `{"error": "LLM chain for topic '...' failed..."}` | LLM parse failure after retry. Check `logs/debug.log` for raw LLM output. |
| `final_report` is empty or missing | Check `compile_report_node` — one or more topic results may be `{"error": ...}`. The node handles unavailable topics gracefully. |
| Stale data for a ticker | Delete `agents/.cache/{TICKER}_{YEAR}/` to force fresh download. |
| `create_financial_manager()` raises `ImportError` | Ensure `langgraph`, `langchain-openai` are installed. `deepagents` is no longer required. |

---

## Design Invariants

1. **`prepare_financial_data` runs exactly once** — topic subgraphs only read the cache.
2. **Subgraphs are stateless** — each only needs `state["cache_key"]`.
3. **All tools return JSON strings, never raise** — errors arrive as `{"error": "..."}`.
4. **Parallel fan-out** — LangGraph executes all 7 subgraphs concurrently; `compile_report` waits for all.
5. **Cache keys are filesystem-safe** — ticker uppercased, year `None` → `"all"`.
6. **Cache root is `__file__`-relative** — independent of caller's `cwd`.
7. **Model propagated via state** — `create_financial_manager(model=...)` injects into `AnalysisState["model"]`; nodes read it from state.
8. **Pydantic v2 serialisation** — `.model_dump()` everywhere.
