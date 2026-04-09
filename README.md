# financialtools

A Python library for fundamental stock analysis. Pipelines Yahoo Finance data through metric computation, sector-weighted scoring, and an LLM synthesis step that returns a structured regime assessment.

## Installation

```bash
pip install -e .
# or
pip install -r requirements.txt
```

Requires a `.env` file with `OPENAI_API_KEY` for the LLM report step.

## Quick start

```python
from financialtools.wrappers import DownloaderWrapper, FundamentalEvaluator
from financialtools.analysis import run_topic_analysis

# 1 — Self-contained: download + evaluate + 8 LLM chains in one call
result = run_topic_analysis("AAPL", sector="Technology", year=2023)
print(result.regime.regime)        # "bull" | "bear"
print(result.liquidity.rating)     # "strong" | "adequate" | "weak"
print(result.red_flags.severity)   # "none" | "low" | "moderate" | "high"

# 2 — Download only
df = DownloaderWrapper.download_data("AAPL")

# 3 — Evaluate only (no LLM)
import pandas as pd
from financialtools.config import sec_sector_metric_weights

sector = "technology"   # yfinance sectorKey convention — lowercase, dashes
weights = pd.DataFrame({
    "sector":  sector,
    "metrics": list(sec_sector_metric_weights[sector].keys()),
    "weights": list(sec_sector_metric_weights[sector].values()),
})
evaluator = FundamentalEvaluator(df=df, weights=weights)
results = evaluator.evaluate_multiple(["AAPL"])

# 4 — Multi-agent hedge fund report (LangGraph)
from agents import create_financial_manager

agent  = create_financial_manager()
config = {"configurable": {"thread_id": "session-1"}}
result = agent.invoke({"ticker": "AAPL", "year": 2023}, config=config)
print(result["final_report"])   # long/short conviction report in markdown
```

## Package layout

**Package (`financialtools/`):**

| Module | Responsibility |
|---|---|
| `processor.py` | `RateLimiter`, `Downloader`, `FundamentalTraderAssistant` |
| `wrappers.py` | `DownloaderWrapper`, `FundamentalEvaluator`, Excel export/read helpers |
| `analysis.py` | `run_topic_analysis()` — self-contained pipeline (download → evaluate → 8 LLM chains) returning `TopicAnalysisResult` |
| `config.py` | Sector weight dicts (single source of truth) |
| `utils.py` | I/O helpers (`export_to_csv`, `export_to_xlsx`, `dataframe_to_json`, `flatten_weights`), yfinance profile helpers |
| `prompts.py` | `build_prompt()` + `build_topic_prompt()` factories + 13 prompt constants |
| `pydantic_models.py` | `StockRegimeAssessment` (regime/valuation); 7 topic models (`LiquidityAssessment` … `RedFlagsAssessment`); `ComprehensiveStockAssessment` |
| `exceptions.py` | `FinancialToolsError`, `DownloadError`, `EvaluationError`, `SectorNotFoundError` |

**Repo root (not part of the installable package):**

| File / Package | Responsibility |
|---|---|
| `chains.py` | LangChain pipeline → `StockRegimeAssessment` (reads from pre-computed Excel output files) |
| `tools.py` | `get_stock_regime_report` `@tool` for LangChain/LangGraph agents; `make_tools(base_dir)` factory |
| `agents/` | LangGraph multi-agent workflow — `create_financial_manager()` runs 7 specialist subgraphs in parallel and produces a hedge-fund-style long/short conviction report |

## Key classes

### `Downloader` (`processor.py`)

```python
d = Downloader.from_ticker("AAPL")
merged_df = d.get_merged_data()   # balance sheet + income + cashflow + market data (long format)
info_df   = d.get_info_data()     # full yfinance info DataFrame (marketCap, forwardPE, etc.)
```

`get_merged_data()` automatically broadcasts `marketcap`, `currentprice`, and
`sharesoutstanding` from `_info` across all time periods — no manual merge needed before
passing to `FundamentalTraderAssistant`.

`from_ticker` raises nothing on failure — returns an empty `Downloader`; `get_merged_data` returns `pd.DataFrame()`.

### `FundamentalTraderAssistant` (`processor.py`)

```python
assistant = FundamentalTraderAssistant(data=merged_df, weights=weights_df)
result = assistant.evaluate()
# result keys: metrics, eval_metrics, composite_scores, raw_red_flags, red_flags, extended_metrics
```

**Raises** `EvaluationError` if `data` is empty, contains multiple tickers, or has NaN-only ticker column.
`evaluate()` returns `_empty_result()` (all 6 keys, fresh empty DataFrames) on any internal failure — never raises.

`evaluate()` return keys:

| Key | Content |
|---|---|
| `metrics` | wide — 24 scored metric columns (original 11 + extended 13) |
| `eval_metrics` | wide — P/E, P/B, P/FCF, EarningsYield, FCFYield |
| `composite_scores` | one row per `(sector, ticker, time)` with `composite_score` |
| `raw_red_flags` | cash-flow quality flags (negative FCF/OCF, EBITDA >> OCF) |
| `red_flags` | threshold-based flags (negative margins, high D/E, etc.) |
| `extended_metrics` | 14 unscored columns: efficiency chain, growth rates, red-flag ratios |

### `FundamentalEvaluator` (`wrappers.py`)

```python
evaluator = FundamentalEvaluator(df=merged_df, weights=weights_df)
results = evaluator.evaluate_multiple(tickers, parallel=True)
```

Uses `ThreadPoolExecutor` for parallel evaluation. Failed tickers return `_empty_result()` and are logged — they do not abort the batch.

### `get_stock_evaluation_report` (`chains.py`, repo root)

```python
from chains import get_stock_evaluation_report

report = get_stock_evaluation_report(
    "AAPL",
    sector="Technology",       # required — caller supplies the sector
    year=2023,                 # optional
    base_dir="financial_data", # directory containing *.xlsx outputs
)
# report: StockRegimeAssessment
```

Reads from `base_dir/*.xlsx`, calls `gpt-4.1-nano` via LangChain. Requires pre-computed Excel files from `export_financial_results()`. Use `run_topic_analysis()` instead if you don't have pre-computed files.

### `run_topic_analysis` (`analysis.py`)

```python
from financialtools.analysis import run_topic_analysis

result = run_topic_analysis(
    "AAPL",
    sector="technology-services",  # yfinance sectorKey convention (sec_sector_metric_weights)
    year=2023,                     # optional — None sends all available years
    model="gpt-4.1-nano",          # OpenAI model (default)
)
# result: TopicAnalysisResult
print(result.regime.regime)           # "bull" | "bear"
print(result.liquidity.rating)        # "strong" | "adequate" | "weak"
print(result.growth.trajectory)       # "accelerating" | "stable" | "decelerating" | "declining"
print(result.red_flags.severity)      # "none" | "low" | "moderate" | "high"
print(result.evaluate_output.keys())  # metrics, eval_metrics, composite_scores, raw_red_flags, red_flags, extended_metrics
```

Runs three stages in one call: download → `FundamentalTraderAssistant.evaluate()` → 8 LLM chains (7 topic models + `StockRegimeAssessment`). No pre-existing Excel files required — data flows directly from yfinance.

**Does not need `financial_data/`** — unlike `get_stock_evaluation_report`, this pipeline is self-contained.

`result.to_dict()` serialises all Pydantic assessments to plain dicts via `.model_dump()`.

Individual topic fields are `None` when the corresponding chain fails; errors are logged as WARNING and processing continues.

## Multi-agent workflow (`agents/`)

A LangGraph `StateGraph` that coordinates 7 specialist subgraphs and compiles a hedge-fund-style long/short conviction report. No Deep Agents dependency — pure LangGraph.

```python
from agents import create_financial_manager

agent  = create_financial_manager(model="gpt-4.1-nano")
config = {"configurable": {"thread_id": "my-session"}}

# Blocking — returns full AnalysisState
result = agent.invoke({"ticker": "BRE.MI", "year": 2023}, config=config)
print(result["final_report"])         # markdown: LONG/SHORT recommendation + deep-dive

# Streaming — observe each subgraph as it completes
for chunk in agent.stream({"ticker": "AAPL"}, config=config, stream_mode="values"):
    print(chunk)
```

**Input keys:** `ticker` (required), `sector` (optional — auto-detected from yfinance), `year` (optional), `model` (optional).

**Output:** `result["final_report"]` — structured markdown with position recommendation, per-topic deep-dives with metric values, long/short theses, and key risks.

The workflow runs the 7 topic subgraphs (`liquidity`, `solvency`, `profitability`, `efficiency`, `cash_flow`, `growth`, `red_flags`) **in parallel**, then synthesises the results in a single `compile_report` node. See `agents/AGENTS.md` for the full architecture.

## Exceptions

```python
from financialtools.exceptions import (
    FinancialToolsError,    # base
    DownloadError,          # yfinance fetch failure
    EvaluationError,        # metric/scoring failure or bad input to __init__
    SectorNotFoundError,    # sector or weight lookup failure (also a ValueError)
)
```

`SectorNotFoundError` inherits from both `FinancialToolsError` and `ValueError`, so existing `except ValueError` blocks continue to work.

## Prompts (`prompts.py`)

Two factories compose prompts from shared metric-definition blocks:

```python
from financialtools.prompts import build_prompt, build_topic_prompt

# Regime / valuation prompt (for StockRegimeAssessment)
prompt = build_prompt(
    sector_aware=True,
    include_red_flags=True,
    include_extended_metrics=True,   # adds 14 unscored extended metrics block
)

# Topic-focused prompt (for the seven topic models)
prompt = build_topic_prompt("liquidity")   # or solvency / profitability / efficiency /
                                           #    cash_flow / growth / red_flags / comprehensive
```

**Regime prompt constants** (for `StockRegimeAssessment`):
- `system_prompt_StockRegimeAssessment`
- `system_prompt_StockRegimeAssessment_sector`
- `system_prompt_noredflags_StockRegimeAssessment`
- `system_prompt_StockRegimeAssessment_extended`
- `system_prompt`

**Topic prompt constants** (one per topic model):
- `system_prompt_liquidity` → `LiquidityAssessment`
- `system_prompt_solvency` → `SolvencyAssessment`
- `system_prompt_profitability` → `ProfitabilityAssessment`
- `system_prompt_efficiency` → `EfficiencyAssessment`
- `system_prompt_cash_flow` → `CashFlowAssessment`
- `system_prompt_growth` → `GrowthAssessment`
- `system_prompt_red_flags` → `RedFlagsAssessment`
- `system_prompt_comprehensive` → `ComprehensiveStockAssessment`

## LangChain / LangGraph agent (`tools.py`, repo root)

One `@tool` function exposes the Excel-based pipeline to a ReAct agent:

| Tool | Description |
|---|---|
| `get_stock_regime_report(ticker, sector, year?)` | Full LLM bull/bear assessment via `chains.py` |

Returns a JSON string; never raises — errors arrive as `{"error": "..."}`.

`base_dir` is **deployment config, not an agent decision** — bake it in at bootstrap time via `make_tools()`.

```python
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from tools import make_tools

tools = make_tools(base_dir="/path/to/my/financial_data")

agent = create_agent(
    model=ChatOpenAI(model="gpt-4o"),
    tools=tools,
    checkpointer=MemorySaver(),
)
config = {"configurable": {"thread_id": "my-session"}, "recursion_limit": 20}
result = agent.invoke(
    {"messages": [{"role": "user", "content": "Assess AAPL Technology for 2023"}]},
    config=config,
)
print(result["messages"][-1].content)
```

Or use the interactive REPL (streams tokens, preserves tool-call history across turns):

```bash
python scripts/run_agent.py
python scripts/run_agent.py --model gpt-4o
```

## Streamlit app (`app.py`)

Interactive web UI for single-ticker topic analysis — no Excel files or pre-computed benchmarks required.

```bash
streamlit run app.py
```

The sidebar accepts ticker, sector (dropdown), optional year filter, and model choice. The pipeline runs with a live progress indicator (download → evaluate → 7 topic chains → regime chain). Results are shown in tabs — one per topic plus an overall regime tab — with coloured rating badges and expandable detail sections.

## CLI (`scripts/run_analysis.py`)

```bash
# List valid sector names
python scripts/run_analysis.py --list-sectors

# Full 8-chain analysis, all years
python scripts/run_analysis.py --ticker AAPL --sector "Technology Services"

# Single year, alternative model
python scripts/run_analysis.py --ticker ENI.MI --sector "Energy Minerals" --year 2023 --model gpt-4o
```

Prints a structured text report to stdout. Exit code 1 on download / evaluation failure.

Required `.env` keys:

```bash
OPENAI_API_KEY=<your-key>

# Optional — enables LangSmith tracing for debugging tool call sequences
LANGSMITH_API_KEY=<your-key>
LANGSMITH_PROJECT=financialtools   # optional, defaults to "default"
```

## Runtime directories (not in repo)

| Path | Contents |
|---|---|
| `financial_data/` | Excel outputs from `export_financial_results()` (required by `chains.py`) |
| `logs/` | `info.log`, `error.log`, `debug.log` — anchored to the package root, not the caller's cwd |

## Running tests

```bash
python -m unittest discover -s tests
```

32 unit tests in `tests/test_processor.py` — all offline (no network, no `.env` required).

## License

MIT
