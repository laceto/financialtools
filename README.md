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
from financialtools.chains import get_stock_evaluation_report

# 1 — Download financial data for a ticker
wrapper = DownloaderWrapper()
df = wrapper.download_data(["AAPL"])

# 2 — Evaluate fundamentals (parallel across tickers)
import pandas as pd
from financialtools.config import sector_metric_weights

sector = "Technology"
weights = (
    pd.DataFrame(list(sector_metric_weights[sector].items()), columns=["metrics", "weights"])
    .assign(sector=sector)
)
evaluator = FundamentalEvaluator(df=df, weights=weights)
results = evaluator.evaluate_multiple(["AAPL"])

# 3 — Generate LLM regime report
report = get_stock_evaluation_report("AAPL", year=2023)
print(report.regime)          # "bull" | "bear"
print(report.regime_rationale)
```

## Package layout

| Module | Responsibility |
|---|---|
| `processor.py` | `RateLimiter`, `Downloader`, `FundamentalTraderAssistant` |
| `wrappers.py` | `DownloaderWrapper`, `FundamentalEvaluator`, file I/O helpers |
| `chains.py` | LangChain pipeline → `StockRegimeAssessment` |
| `config.py` | Sector weight dicts (single source of truth) |
| `utils.py` | I/O helpers, ticker/sector lookups, `get_fin_data`, `list_evaluated_tickers` |
| `tools.py` | Five `@tool` functions for LangChain/LangGraph agents |
| `prompts.py` | `build_prompt()` + `build_topic_prompt()` factories + 13 prompt constants |
| `pydantic_models.py` | `StockRegimeAssessment` (regime/valuation); 7 topic models (`LiquidityAssessment` … `RedFlagsAssessment`); `ComprehensiveStockAssessment` |
| `exceptions.py` | `FinancialToolsError`, `DownloadError`, `EvaluationError`, `SectorNotFoundError` |

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

### `get_stock_evaluation_report` (`chains.py`)

```python
report = get_stock_evaluation_report(
    "AAPL",
    year=2023,
    base_dir="financial_data",          # directory containing *.xlsx outputs
    sector_file="financialtools/data/sector_ticker.txt",  # ticker→sector mapping
)
# report: StockRegimeAssessment
```

Reads from `base_dir/*.xlsx`, fetches sector benchmarks, calls `gpt-4.1-nano` via LangChain.
External consumers pass their own `base_dir` and `sector_file` paths.

### `get_fin_data` (`utils.py`)

```python
metrics_json, composite_json, red_flags_json = get_fin_data(
    ticker="AAPL",
    year=2023,                    # optional — filters metrics and red flags
    base_dir="financial_data",    # default: runtime output dir
    round_metrics=False,          # set True for 2-decimal rounding
)
```

`get_fin_data_year(ticker, year)` is a backward-compatible alias that sets `base_dir="financial_data"` and `round_metrics=True`.

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

## LangChain / LangGraph agent (`tools.py`)

Five `@tool` functions expose the full pipeline to a ReAct agent:

| Tool | Description |
|---|---|
| `list_available_tickers()` | Sorted list of evaluated tickers from `composite_scores.xlsx` |
| `get_stock_metrics(ticker, year?)` | Metrics + composite score + red flags as JSON |
| `get_sector_benchmarks(sector)` | Peer-average financial and valuation metrics |
| `get_red_flags(ticker)` | Red-flag warnings across all years |
| `get_stock_regime_report(ticker, year?)` | Full LLM bull/bear assessment via `chains.py` |

All tools return JSON strings and never raise — errors arrive as `{"error": "..."}`.

File paths (data directory, sector mapping file) are **deployment config, not agent
decisions** — bake them in at bootstrap time via `make_tools()`, never expose them
as tool parameters.

```python
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from financialtools.tools import make_tools

# In-repo default (financial_data/ relative to CWD):
# from financialtools.tools import TOOLS

# External consumer — explicit paths:
tools = make_tools(
    base_dir="/path/to/my/financial_data",
    sector_file="/path/to/my/sector_ticker.txt",
)

agent = create_agent(
    model=ChatOpenAI(model="gpt-4o"),
    tools=tools,
    checkpointer=MemorySaver(),
)
config = {"configurable": {"thread_id": "my-session"}, "recursion_limit": 20}
result = agent.invoke(
    {"messages": [{"role": "user", "content": "Assess AAPL for 2023"}]},
    config=config,
)
print(result["messages"][-1].content)
```

Or use the interactive REPL (streams tokens, preserves tool-call history across turns):

```bash
python scripts/run_agent.py
python scripts/run_agent.py --model gpt-4o
```

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
| `financial_data/` | Excel outputs from `export_financial_results()` and sector benchmark files |
| `logs/` | `info.log`, `error.log`, `debug.log` — anchored to the package root, not the caller's cwd |
| `financialtools/data/weights.xlsx` | Optional external sector weights file (loaded by callers, not by the package itself) |

## Running tests

```bash
python -m unittest discover -s tests
```

32 unit tests in `tests/test_processor.py` — all offline (no network, no `.env` required).

## License

MIT
