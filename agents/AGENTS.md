# Financial Analysis Agent System

> **Module:** `agents/`
> **Added:** March 2026
> **Entry point:** `from agents import create_financial_manager`

---

## Overview

The `agents/` package implements a **manager + specialist subagent** architecture built on [Deep Agents](https://github.com/anthropics/deep-agents).

A single **Financial Analysis Manager** orchestrates seven **topic subagents**, each responsible for exactly one area of fundamental analysis. The manager downloads and evaluates financial data once, serialises the results to a **disk cache**, then delegates LLM analysis in parallel to each specialist. This design avoids redundant yfinance calls and keeps subagents completely stateless.

```
Financial Analysis Manager (Deep Agent)
├── Tool: prepare_financial_data         ← downloads + evaluates, writes cache
├── Subagents (7 topic specialists)
│   ├── liquidity_analyst    → run_liquidity_analysis
│   ├── solvency_analyst     → run_solvency_analysis
│   ├── profitability_analyst → run_profitability_analysis
│   ├── efficiency_analyst   → run_efficiency_analysis
│   ├── cash_flow_analyst    → run_cash_flow_analysis
│   ├── growth_analyst       → run_growth_analysis
│   └── red_flags_analyst    → run_red_flags_analysis
└── Built-in (Deep Agents harness)
    ├── write_todos           ← task planning
    ├── task                  ← subagent delegation
    └── filesystem tools      ← ls, read_file, write_file, …
```

---

## Module Map

| File | Responsibility |
|---|---|
| `__init__.py` | Re-exports `create_financial_manager` as the public API |
| `financial_agent.py` | Manager factory (`create_financial_manager`), system prompt |
| `_subagents.py` | `build_topic_subagents()` — builds the seven subagent dicts |
| `_tools/data_tools.py` | `prepare_financial_data` tool (manager only) |
| `_tools/topic_tools.py` | Seven `run_*_analysis` tools (one per subagent) + `TOPIC_TOOLS` map |
| `_cache.py` | Disk-based payload cache — `cache_key`, `write_payloads`, `read_payloads`, `write_topic_result`, `read_topic_result` |

---

## Orchestration Flow

```
1. User sends request: "Analyse AAPL for sector Technology, year 2023"
   │
2. Manager plans 9 todos (via write_todos):
   │   "Prepare financial data", "Liquidity analysis", … , "Compile final report"
   │
3. Manager calls prepare_financial_data(ticker="AAPL", sector="Technology", year=2023)
   │   → Downloader.from_ticker("AAPL").get_merged_data()
   │   → FundamentalTraderAssistant.evaluate()  [24 scored + 14 unscored metrics]
   │   → normalise_time + filter_year
   │   → writes agents/.cache/AAPL_2023/payloads.json
   │   → returns {"cache_key": "AAPL_2023", "status": "ready"}
   │
4. Manager delegates each topic:
   │   task(agent="liquidity_analyst",
   │        instruction="Run liquidity analysis. cache_key=AAPL_2023. Return full JSON.")
   │   … (×7 topics)
   │
5. Each subagent:
   │   → reads agents/.cache/AAPL_2023/payloads.json
   │   → invokes its LangChain topic chain (with one-shot fix retry)
   │   → writes agents/.cache/AAPL_2023/{topic}.json
   │   → returns assessment JSON to manager
   │
6. Manager compiles structured markdown report:
       Overall regime signal · Per-topic summaries · Top 3 concerns
```

---

## Manager Agent

**Source:** `agents/financial_agent.py`

### Factory

```python
create_financial_manager(
    model: str = "gpt-4.1-nano",
    checkpointer = None,          # defaults to MemorySaver()
) -> LangGraph Runnable
```

**Args:**

| Param | Default | Description |
|---|---|---|
| `model` | `"gpt-4.1-nano"` | LLM used by both the manager and all subagents |
| `checkpointer` | `MemorySaver()` | LangGraph checkpointer for session continuity. Pass `SqliteSaver` or `PostgresSaver` for durable persistence across process restarts |

**Returns:** A compiled Deep Agent (LangGraph `Runnable`).

### Usage

```python
from agents import create_financial_manager

agent = create_financial_manager()

result = agent.invoke(
    {"messages": [{"role": "user", "content":
        "Analyse AAPL for sector Technology, year 2023"}]},
    config={"configurable": {"thread_id": "session-1"}},
)
print(result["messages"][-1].content)
```

**`thread_id`** identifies the session. Reuse the same ID across calls to maintain conversation continuity within the checkpointer's scope.

### System Prompt Behaviour

The manager is instructed to:
1. Always start with a 9-task plan via `write_todos`.
2. Call `prepare_financial_data` before any subagent delegation.
3. Include the `cache_key` in every subagent instruction (it is required for cache reads).
4. Delegate all 7 topics — no topics may be skipped.
5. Compile results into a structured markdown report with regime signal, per-topic summaries, and top concerns.

---

## Subagents

**Source:** `agents/_subagents.py`

### Factory

```python
build_topic_subagents(model: str = "gpt-4.1-nano") -> list[dict]
```

Returns a list of 7 subagent dicts accepted by `create_deep_agent(subagents=...)`.

Each dict has the shape:

```python
{
    "name":          str,   # e.g. "liquidity_analyst"
    "description":   str,   # used by the manager to pick the right specialist
    "system_prompt": str,   # role + tool usage instruction
    "model":         str,
    "tools":         [tool_fn],  # exactly one tool per subagent
}
```

### Subagent Inventory

| Subagent | Metrics covered | Tool |
|---|---|---|
| `liquidity_analyst` | CurrentRatio, QuickRatio, CashRatio, WorkingCapitalRatio; DSO, DIO, DPO, CCC | `run_liquidity_analysis` |
| `solvency_analyst` | DebtToEquity, DebtRatio, EquityRatio, NetDebtToEBITDA, InterestCoverage; DebtGrowth | `run_solvency_analysis` |
| `profitability_analyst` | GrossMargin, OperatingMargin, NetProfitMargin, EBITDAMargin, ROA, ROE, ROIC; Accruals | `run_profitability_analysis` |
| `efficiency_analyst` | AssetTurnover; ReceivablesTurnover, DSO, InventoryTurnover, DIO, PayablesTurnover, DPO, CCC | `run_efficiency_analysis` |
| `cash_flow_analyst` | FCFToRevenue, FCFYield, FCFtoDebt, OCFRatio, FCFMargin, CashConversion, CapexRatio; FCFGrowth, CapexToDepreciation | `run_cash_flow_analysis` |
| `growth_analyst` | RevenueGrowth, NetIncomeGrowth, FCFGrowth; Dilution | `run_growth_analysis` |
| `red_flags_analyst` | Raw FCF/OCF flags, threshold flags (negative margins, high D/E, negative ROA/ROE); Accruals, DebtGrowth, Dilution, CapexToDepreciation | `run_red_flags_analysis` |

### Design Invariants

- Each subagent has **exactly one tool** matching its specialty — it cannot call tools it was not given.
- Subagents are **stateless**: the manager must embed the `cache_key` in every delegation instruction.
- System prompts are intentionally concise (role statement + tool usage instruction). The LLM analysis depth is driven by the topic prompt inside the tool, not by the system prompt.

---

## Tools

### Manager Tool — `prepare_financial_data`

**Source:** `agents/_tools/data_tools.py`

**Given to:** Manager only (not subagents).

```python
@tool
def prepare_financial_data(ticker: str, sector: str, year: int | None = None) -> str:
```

**Stages:**

| Stage | Action |
|---|---|
| 1. Download | `Downloader.from_ticker(ticker).get_merged_data()` |
| 2. Evaluate | `FundamentalTraderAssistant(merged, weights).evaluate()` — 24 scored + 14 unscored metrics |
| 3. Normalise | `_normalise_time()` + `_filter_year()` per output DataFrame |
| 4. Cache | `write_payloads(cache_key, {...})` → `agents/.cache/{KEY}/payloads.json` |

**Returns (success):**
```json
{"cache_key": "AAPL_2023", "ticker": "AAPL", "sector": "Technology", "year": 2023, "status": "ready"}
```

**Returns (failure):**
```json
{"error": "<descriptive message>"}
```

Failures: empty download, `EvaluationError` (bad ticker/weights), any unexpected exception. Never raises — errors arrive as JSON.

**Logging:** `[prepare_financial_data] ticker=... sector=... year=...` on start; `cache written → key=...` on success; `EvaluationError: ...` on evaluation failure.

---

### Topic Tools — `run_*_analysis`

**Source:** `agents/_tools/topic_tools.py`

**Given to:** One subagent each (see table above).

All seven tools share the same implementation via `_run_topic(cache_key, topic)`:

```
1. read_payloads(cache_key)                 → dict (raises FileNotFoundError if missing)
2. _build_topic_chain(topic, llm)           → (prompt, PydanticOutputParser)
3. _invoke_chain(prompt, parser, llm, ...)  → Pydantic assessment | None  [one-shot fix retry]
4. write_topic_result(cache_key, topic, assessment.model_dump())
5. return json.dumps(assessment.model_dump())
```

**Model override:** Set `TOPIC_TOOLS_MODEL` env variable at process start to override the default `gpt-4.1-nano` for all topic tools (e.g. for cheaper testing).

**Tool signatures and return schemas:**

| Tool | `cache_key` arg | Key return fields |
|---|---|---|
| `run_liquidity_analysis` | Identifier from `prepare_financial_data` | `rating` ("strong"\|"adequate"\|"weak"), `rationale`, `working_capital_efficiency`, `concerns` |
| `run_solvency_analysis` | same | `rating`, `rationale`, `debt_trend`, `concerns` |
| `run_profitability_analysis` | same | `rating`, `rationale`, `earnings_quality`, `concerns` |
| `run_efficiency_analysis` | same | `rating`, `rationale`, `working_capital_chain`, `concerns` |
| `run_cash_flow_analysis` | same | `rating`, `rationale`, `capital_allocation`, `concerns` |
| `run_growth_analysis` | same | `trajectory` ("accelerating"\|"stable"\|"decelerating"\|"declining"), `rationale`, `dilution_impact`, `concerns` |
| `run_red_flags_analysis` | same | `severity` ("none"\|"low"\|"moderate"\|"high"), `rationale`, `cash_flow_flags`, `threshold_flags`, `quality_concerns` |

**`TOPIC_TOOLS` dict** (convenience map used by `_subagents.py`):
```python
TOPIC_TOOLS = {
    "liquidity":     run_liquidity_analysis,
    "solvency":      run_solvency_analysis,
    "profitability": run_profitability_analysis,
    "efficiency":    run_efficiency_analysis,
    "cash_flow":     run_cash_flow_analysis,
    "growth":        run_growth_analysis,
    "red_flags":     run_red_flags_analysis,
}
```

**Error handling:** All tools return `{"error": "..."}` on any failure — `FileNotFoundError` on cache miss, LLM chain failure after retry, or unexpected exceptions. Never raise.

---

## Cache

**Source:** `agents/_cache.py`

### Purpose

Decouples the download/evaluate stage (run once by the manager) from the LLM analysis stage (run once per topic by each subagent). Subagents never call yfinance — they read pre-computed JSON payloads from disk.

### Layout

```
agents/.cache/
└── {TICKER}_{YEAR}/
    ├── payloads.json        # five LLM input payloads + metadata (written by manager)
    ├── liquidity.json       # LiquidityAssessment result (written by subagent)
    ├── solvency.json
    ├── profitability.json
    ├── efficiency.json
    ├── cash_flow.json
    ├── growth.json
    └── red_flags.json
```

The cache root is resolved relative to `_cache.py` (`agents/.cache/`), independent of the caller's working directory.

### Public API

```python
from agents._cache import (
    cache_key,
    write_payloads,
    read_payloads,
    write_topic_result,
    read_topic_result,
)
```

#### `cache_key(ticker, year) → str`

Builds a filesystem-safe cache identifier.

```python
cache_key("AAPL", 2023)   # → "AAPL_2023"
cache_key("eni.mi", None) # → "ENI.MI_all"
cache_key("msft", None)   # → "MSFT_all"
```

Ticker is uppercased. Year `None` → `"all"` (all available periods).

#### `write_payloads(key, data) → None`

Writes `agents/.cache/{key}/payloads.json`. Creates the directory if it does not exist.

Expected `data` keys:
```
ticker, sector, year,
metrics, extended_metrics, composite_scores, eval_metrics, red_flags
```
All `metrics` values are JSON strings (from `dataframe_to_json()`).

#### `read_payloads(key) → dict`

Reads `agents/.cache/{key}/payloads.json`.

**Raises `FileNotFoundError`** if the key has not been written yet. Callers (topic tools) catch this and return `{"error": ...}`.

#### `write_topic_result(key, topic, data) → None`

Writes `agents/.cache/{key}/{topic}.json`. Topic is any string matching `TOPIC_TOOLS` keys.

#### `read_topic_result(key, topic) → dict | None`

Reads a topic result. Returns `None` if not yet written (no error raised). Use this to check whether a subagent has already completed a topic (e.g., before re-delegating).

### Cache Lifetime

The cache is **not automatically invalidated**. Entries persist until manually deleted. Re-running an analysis for the same `ticker + year` combination overwrites `payloads.json` and each topic file.

---

## Environment Variables

| Variable | Default | Effect |
|---|---|---|
| `OPENAI_API_KEY` | _(required)_ | OpenAI key for all LLM calls. Loaded via `python-dotenv` in `topic_tools.py`. |
| `TOPIC_TOOLS_MODEL` | `"gpt-4.1-nano"` | Override LLM model for all seven topic tools at import time. |

---

## Tests

**Source:** `tests/test_financial_agent.py`

| Test class | What it covers |
|---|---|
| `TestCacheUtils` | `cache_key` normalisation; `write`/`read` payloads roundtrip; `FileNotFoundError` on missing key; `write`/`read` topic result roundtrip; `None` on missing topic result |
| `TestPrepareFinancialDataTool` | Empty download → error JSON; `EvaluationError` → error JSON; happy path → `cache_key` + `status: ready` in result, `write_payloads` called once |
| `TestTopicTools` | All 7 topics present in `TOPIC_TOOLS`; missing cache key → error JSON (no exception raised) |
| `TestSubagents` | 7 subagents built; required keys present in each; each has exactly one tool; names are unique |
| `TestManagerAgent` | `create_financial_manager()` constructs without raising; custom model accepted |

Run:
```bash
python -m unittest tests/test_financial_agent.py
```

---

## Debugging Guide

| Symptom | Where to look |
|---|---|
| `{"error": "No financial data returned for ticker '...'}` from `prepare_financial_data` | Verify the ticker symbol and network connectivity. Check `logs/error.log`. |
| `{"error": "EvaluationError: ..."}` from `prepare_financial_data` | Ticker or sector name is invalid. Check `EvaluationError` message — it names the exact problem (empty data, multi-ticker, bad weights). |
| Topic tool returns `{"error": "No cached payloads for key '...'. Call prepare_financial_data first."}` | Manager did not include the correct `cache_key` in the subagent instruction, or `prepare_financial_data` was not called before delegation. |
| Topic tool returns `{"error": "LLM chain for topic '...' failed after fix retry — see logs."}` | The LLM returned output that could not be parsed as the expected Pydantic model even after one fix retry. Check `logs/debug.log` for the raw LLM response. |
| Stale data returned for a ticker | Cache is not invalidated automatically. Delete `agents/.cache/{TICKER}_{YEAR}/` to force a fresh download. |
| Subagent receives wrong tool | Check `_SUBAGENT_META` in `_subagents.py` — the third element of each tuple is the `TOPIC_TOOLS` key. Verify the key matches exactly. |
| `create_financial_manager()` hangs on construction | Deep Agents compile step — check that `deepagents` is installed and that `OPENAI_API_KEY` is set. |

---

## Design Invariants (summary)

1. **`prepare_financial_data` runs exactly once per request** — subagents only read the cache.
2. **Subagents are stateless** — the manager must pass `cache_key` explicitly in every delegation instruction.
3. **All tools return JSON strings, never raise** — errors arrive as `{"error": "..."}`.
4. **Each subagent has exactly one tool** — no cross-topic access.
5. **Cache keys are filesystem-safe** — ticker uppercased, year `None` → `"all"`.
6. **Cache root is `__file__`-relative** — independent of caller's `cwd`.
7. **LLM model is configurable at construction time** — `create_financial_manager(model=...)` propagates to all subagents. Topic tools additionally accept `TOPIC_TOOLS_MODEL` env override.
8. **Pydantic v2 serialisation** — `.model_dump()` everywhere (not `.dict()`).
