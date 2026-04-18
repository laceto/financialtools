# Financial Analysis Agent System

> **Module:** `agents/`
> **Entry point:** `from agents import create_financial_manager`

---

## Overview

The `agents/` package implements a **manager + 7 specialist subgraph** architecture built on **LangGraph's native `StateGraph`**.

A single `AnalysisState` flows through the main graph. After a data preparation node writes the cache, seven topic subgraphs execute **in parallel**, each appending its result to state. A final compile node synthesises all results into a structured markdown report.

```
START ──► prepare_data ──┬──► liquidity_analyst             ──┐
                         ├──► solvency_analyst              ──┤
                         ├──► profitability_analyst         ──┤
                         ├──► efficiency_analyst            ──┤  (parallel)
                         ├──► cash_flow_analyst             ──┤
                         ├──► growth_analyst                ──┤
                         ├──► red_flags_analyst             ──┤
                         └──► quantitative_overview_analyst ──┴──► compile_report ──► END
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

3. prepare_data node  → calls _download_and_evaluate(ticker, sector, year)
   │   → Downloader.from_ticker("AAPL").get_merged_data()
   │   → FundamentalMetricsEvaluator.evaluate()  [24 scored + 14 unscored metrics]
   │   → normalise_time + filter_year
   │   → writes agents/.cache/AAPL_2023/payloads.json  ← observability side-effect
   │   → state ← {cache_key, company_name, resolved_sector,
   │              metrics_json, extended_metrics_json, eval_metrics_json,
   │              composite_scores_json, red_flags_json}

4. 7 topic subgraphs run in parallel, each:
   │   → reads payload fields directly from state (no disk reads)
   │   → calls _analyse_topic(payloads, topic, model)
   │   → invokes LangChain topic chain (with one-shot fix retry)
   │   → writes agents/.cache/AAPL_2023/{topic}.json  ← observability side-effect
   │   → state ← {topic}_result: {...}

5. compile_report node (runs after all 7 complete)
   │   → LLM call with all 7 topic results
   │   → state ← {final_report: "## Overall Assessment ..."}

6. result["final_report"] is the structured markdown report
```

### Data channel: state, not disk

The five `*_json` fields in `AnalysisState` are the **only** data channel between
`prepare_data_node` and the topic subgraphs.  The disk cache is written as a
write-only observability side-effect — topic subgraphs never call `read_payloads`.

```
prepare_data_node
    ↓  writes to state
    metrics_json, extended_metrics_json, eval_metrics_json,
    composite_scores_json, red_flags_json
    ↓  also writes to disk (side-effect for debugging)
    agents/.cache/{KEY}/payloads.json

liquidity_analyst (and 6 others)
    ← reads *_json fields from state   (primary path)
    ↓  writes to disk (side-effect)
    agents/.cache/{KEY}/liquidity.json
```

The `@tool` wrappers (`run_*_analysis`) still go through the disk cache —
they exist for backward compatibility and CLI use, not for the graph hot path.

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
    # After prepare_data — metadata
    cache_key:       str
    company_name:    str      # lowercased longName, e.g. "apple inc."
    resolved_sector: str      # final sector used (auto-detected or caller-supplied)
    # After prepare_data — data payloads (primary channel to topic subgraphs)
    metrics_json:           str   # FundamentalMetricsEvaluator scored metrics
    extended_metrics_json:  str   # unscored / quality metrics
    eval_metrics_json:      str   # per-metric scores and flags
    composite_scores_json:  str   # weighted composite scores per period
    red_flags_json:         str   # threshold and cash-flow red flags
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

`run_analysis` reads the five `*_json` payload fields **directly from state** (no disk read),
builds a `payloads` dict, and calls `_analyse_topic(payloads, topic, model)`.
Writes `state["{topic}_result"]`.

| Subgraph node | Tool called (disk-cache path) | State key written |
|---|---|---|
| `liquidity_analyst` | `run_liquidity_analysis` | `liquidity_result` |
| `solvency_analyst` | `run_solvency_analysis` | `solvency_result` |
| `profitability_analyst` | `run_profitability_analysis` | `profitability_result` |
| `efficiency_analyst` | `run_efficiency_analysis` | `efficiency_result` |
| `cash_flow_analyst` | `run_cash_flow_analysis` | `cash_flow_result` |
| `growth_analyst` | `run_growth_analysis` | `growth_result` |
| `red_flags_analyst` | `run_red_flags_analysis` | `red_flags_result` |
| `quantitative_overview_analyst` | `run_quantitative_overview_analysis` | `quantitative_overview_result` |

**Note:** In the graph hot path, subgraph nodes call `_analyse_topic` directly (payloads from state).
The "Tool called" column refers to the `@tool` wrappers available for CLI / direct use.

---

## Tools

### `_download_and_evaluate` / `prepare_financial_data`

**Source:** `agents/_tools/data_tools.py`

`_download_and_evaluate(ticker, sector, year) → dict` is the core pipeline — a plain Python
function called directly by `prepare_data_node`.  It raises on failure.

| Stage | Action |
|---|---|
| 1. Download | `Downloader.from_ticker(ticker).get_merged_data()` |
| 1b. Enrich | `longName` → `company_name`; `sector` auto-detected from `sectorKey` if not supplied |
| 2. Evaluate | `FundamentalMetricsEvaluator.evaluate()` — 24 scored + 14 unscored metrics |
| 3. Normalise | `_normalise_time()` + `_filter_year()` per DataFrame |
| 4. Cache | `write_payloads(cache_key, {...})` → `agents/.cache/{KEY}/payloads.json` (side-effect) |

Returns a Python dict with all five payload JSON strings plus metadata.

`prepare_financial_data` is a thin `@tool` wrapper — returns metadata JSON only, catches all
exceptions as `{"error": "..."}`.  Exists for backward compatibility and tests.

### Topic Tools — `_analyse_topic` / `run_*_analysis`

**Source:** `agents/_tools/topic_tools.py`

`_analyse_topic(payloads, topic, model) → str` is the core LLM implementation — accepts a
`payloads` dict directly (from state), never raises.

```
_analyse_topic(payloads, topic, model)
    → _build_topic_chain(topic, llm)
    → _invoke_chain(...)
    → write_topic_result(...)  ← side-effect
    → returns JSON string
```

`_run_topic(cache_key, topic)` is a shim: `read_payloads(cache_key) → _analyse_topic(...)`.
Used only by the `@tool` wrappers for backward compatibility and CLI use.

| Tool | Key return fields |
|---|---|
| `run_liquidity_analysis` | `rating`, `rationale`, `working_capital_efficiency`, `concerns` |
| `run_solvency_analysis` | `rating`, `rationale`, `debt_trend`, `concerns` |
| `run_profitability_analysis` | `rating`, `rationale`, `earnings_quality`, `concerns` |
| `run_efficiency_analysis` | `rating`, `rationale`, `working_capital_chain`, `concerns` |
| `run_cash_flow_analysis` | `rating`, `rationale`, `capital_allocation`, `concerns` |
| `run_growth_analysis` | `trajectory`, `rationale`, `dilution_impact`, `concerns` |
| `run_red_flags_analysis` | `severity`, `rationale`, `cash_flow_flags`, `threshold_flags`, `quality_concerns` |
| `run_quantitative_overview_analysis` | `overall_rating`, `composite_trend`, `composite_trend_rationale`, `scoring_profile`, `valuation_context`, `cross_dimensional_signals`, `data_completeness`, `concerns` |

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
| Topic subgraph result is `{"error": "No cached payloads..."}` | Only reachable via `@tool` wrappers (CLI use). Inside the graph, subgraphs read from state — if `metrics_json` is absent, `prepare_data_node` raised and the graph stopped. Check the `ValueError` message. |
| Topic result is `{"error": "LLM chain for topic '...' failed..."}` | LLM parse failure after retry. Check `logs/debug.log` for raw LLM output. |
| `final_report` is empty or missing | Check `compile_report_node` — one or more topic results may be `{"error": ...}`. The node handles unavailable topics gracefully. |
| Stale data for a ticker | Delete `agents/.cache/{TICKER}_{YEAR}/` to force fresh download. |
| `create_financial_manager()` raises `ImportError` | Ensure `langgraph`, `langchain-openai` are installed. `deepagents` is no longer required. |

---

## Design Invariants

1. **Download runs exactly once** — `_download_and_evaluate` is called only in `prepare_data_node`.
2. **State is the data channel** — topic subgraphs read the five `*_json` fields from state; no `read_payloads` in the hot path.
3. **Disk cache is write-only during a graph run** — `write_payloads` and `write_topic_result` are called for observability; `read_payloads` is only called by the `@tool` wrappers (backward compat/CLI).
4. **`_analyse_topic` is the single LLM impl** — both subgraph nodes and `@tool` wrappers call it; no duplication.
5. **All topic functions never raise** — errors arrive as `{"error": "..."}` in `{topic}_result`.
6. **`prepare_data_node` raises on failure** — download/evaluation errors surface immediately as `ValueError`.
7. **Parallel fan-out** — LangGraph executes all 7 subgraphs concurrently; `compile_report` waits for all.
8. **Cache keys are filesystem-safe** — ticker uppercased, year `None` → `"all"`.
9. **Cache root is `__file__`-relative** — independent of caller's `cwd`.
10. **Model propagated via state** — `create_financial_manager(model=...)` injects into `AnalysisState["model"]`; all nodes read it from state.
11. **Pydantic v2 serialisation** — `.model_dump()` everywhere.
