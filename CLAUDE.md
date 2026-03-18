# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install the package (editable mode for development)
pip install -e .

# Install all dependencies
pip install -r requirements.txt

# Run a single test file
python -m unittest tests/test_processor.py

# Run all tests
python -m unittest discover -s tests
```

No Makefile, no dedicated lint/format tooling is configured. Add `ruff` or `black` if needed.

## Architecture

This is a **fundamental stock analysis library** that pipelines three concerns:

1. **Data acquisition** — fetch and reshape Yahoo Finance data into long-format DataFrames
2. **Metric evaluation** — compute and score 11 financial metrics using sector-weighted rubrics
3. **LLM synthesis** — send scored results to GPT-4.1-nano via LangChain and return a structured `StockRegimeAssessment`

### Module responsibilities

| Module | Responsibility |
|---|---|
| `processor.py` | `RateLimiter` (thread-safe sliding-window), `Downloader` (yfinance fetch + wide→long reshape), `FundamentalTraderAssistant` (metric computation, 1-5 scoring, red-flag detection) |
| `config.py` | Sector-specific metric weight dicts (`grouped_weights`, `sector_metric_weights`, `sec_sector_metric_weights`). Single source of truth for all scoring weights. No I/O at import time — pure Python dicts. |
| `utils.py` | I/O helpers (Excel/CSV), ticker/sector lookups (`get_sector_for_ticker`, `get_market_metrics`), DataFrame→JSON conversion, `get_fin_data`, `list_evaluated_tickers` |
| `tools.py` | Five `@tool` functions for LangChain/LangGraph agents: `list_available_tickers`, `get_stock_metrics`, `get_sector_benchmarks`, `get_red_flags`, `get_stock_regime_report`. All return JSON strings and never raise. `TOOLS` list is the canonical import for agent bootstraps. |
| `wrappers.py` | `DownloaderWrapper` (public download API, logs to `logs/`), `FundamentalEvaluator` (parallel evaluation via `ThreadPoolExecutor`), Excel export/read helpers |
| `chains.py` | LangChain pipeline: reads Excel results → loads sector benchmarks → invokes `gpt-4.1-nano` → returns `StockRegimeAssessment` |
| `pydantic_models.py` | `StockRegimeAssessment`: validated LLM output (regime, evaluation, rationale, market comparison) |
| `prompts.py` | `build_prompt(sector_aware, include_red_flags)` factory + four ready-made prompt constants. Shared metric-definition blocks (`_FINANCIAL_METRICS_BLOCK`, `_EVAL_METRICS_BLOCK`, etc.) are the single source of truth for metric descriptions. |
| `exceptions.py` | `FinancialToolsError` (base), `DownloadError`, `EvaluationError`, `SectorNotFoundError` (also a `ValueError`) |

### Key data flows

**Download:**
```
Ticker → Downloader.from_ticker() → yfinance
  → balance_sheet / income_stmt / cashflow (wide → long via __reshape_fin_data)
  → get_merged_data() → single merged DataFrame
  → DownloaderWrapper.download_data() → saves to logs/, returns pandas DataFrame
```

**Evaluate:**
```
merged_df + weights → FundamentalTraderAssistant(data, weights)  # raises EvaluationError on bad input
  → evaluate()
      → compute_metrics()           # produces metric columns + sector
      → compute_valuation_metrics() # P/E, P/B, P/FCF, EarningsYield → self.eval_metrics
      → raw_red_flags()             # cash-flow red flags
      → melt(value_vars=<dynamic: all non-id cols from compute_metrics()>) → m_long
      → score_metric(m_long)        # 1–5 per metric (returns copy — does not mutate input)
      → merge(self.weights)         # adds sector + weights columns; warns on NaN weights
      → _compute_composite_scores() # → self.scores (wide: sector, ticker, time, composite_score)
      → metrics_red_flags(m_long)   # → self.red_flags (returns copy — does not mutate input)
      → returns dict with keys: metrics, eval_metrics, composite_scores, raw_red_flags, red_flags
      → on any failure: returns _empty_result() (all keys, fresh empty DataFrames) + logs error
  → compute_scores()            # standalone: melt(dynamic cols) → score_metric → self.metric_scores
                                #   (long format, one row per ticker/time/metric — NOT self.scores)
  → export_financial_results()  → financial_data/*.xlsx
```

**Score attribute schema — do not conflate:**
- `self.metric_scores` — long format, set by `compute_scores()`, columns: ticker, time, metrics, value, score, sector
- `self.scores` — wide format, set by `evaluate()`, columns: sector, ticker, time, composite_score

**LLM report:**
```
get_stock_evaluation_report(ticker, year?)
  → read_financial_results() from financial_data/*.xlsx
  → get_sector_for_ticker() + get_market_metrics()
  → LangChain: ChatPromptTemplate | ChatOpenAI | OutputFixingParser
  → StockRegimeAssessment (regime, evaluation, rationale, market_comparison)
```

**Agent (tools.py):**
```
TOOLS = [list_available_tickers, get_stock_metrics, get_sector_benchmarks,
         get_red_flags, get_stock_regime_report]

create_agent(model=llm, tools=TOOLS, checkpointer=MemorySaver())
  list_available_tickers()       → list_evaluated_tickers() → JSON array
  get_stock_metrics(ticker,year) → get_fin_data()            → JSON {metrics, composite_scores, red_flags}
  get_sector_benchmarks(sector)  → get_market_metrics() ×2  → JSON {financial, valuation}
  get_red_flags(ticker)          → get_fin_data()            → JSON {red_flags}
  get_stock_regime_report(t,yr)  → get_stock_evaluation_report() → JSON (model_dump())
```

All tools: return JSON strings, never raise; errors arrive as `{"error": "..."}`.
Pydantic serialisation: `.model_dump()` (not `.dict()` — Pydantic v2).
Agent: `create_agent` from `langchain.agents` (LangChain 1.0 LTS). Persistence via `MemorySaver` checkpointer + `thread_id` config. Recursion capped at 20.

### Runtime data directories (not in repo)

- `financial_data/` — Excel outputs from `export_financial_results()` and sector benchmark files (`metrics_by_sectors.xlsx`, `eval_metrics_by_sectors.xlsx`)
- `logs/` — `info.log`, `error.log`, `debug.log` written by `DownloaderWrapper`. Path is anchored to `os.path.dirname(__file__)/../logs` — independent of caller's cwd.
- `financialtools/data/weights.xlsx` — external sector weights file; loaded by callers (e.g. via `pd.read_excel`), not by `config.py` at import time

### Environment

Requires a `.env` file with `OPENAI_API_KEY` (loaded via `python-dotenv` in `chains.py`).

### Scoring invariant

All composite scores are computed as:
```
score = sum(metric_score_i * weight_i) / sum(weight_i)
```
where `metric_score_i ∈ {1, 2, 3, 4, 5}`. Higher is better. Sector weights come from `config.sector_metric_weights`; fall back to `config.grouped_weights` if the sector is not mapped.

The 11 scored metrics are the columns produced by `compute_metrics()`:
`GrossMargin, OperatingMargin, NetProfitMargin, EBITDAMargin, ROA, ROE, FCFToRevenue, FCFYield, FCFtoDebt, DebtToEquity, CurrentRatio`

`SCORED_METRICS` (module-level constant in `processor.py`) lists the same names for reference, but `evaluate()` and `compute_scores()` derive `value_vars` dynamically from `compute_metrics()` output columns — adding a metric to `compute_metrics()` automatically includes it in scoring without touching `SCORED_METRICS`.

### Exceptions

```python
from financialtools.exceptions import SectorNotFoundError, EvaluationError, DownloadError
```

- `SectorNotFoundError` — raised by `get_sector_for_ticker`, `get_market_metrics`. Inherits `ValueError` so `except ValueError` blocks still work.
- `EvaluationError` — raised by `FundamentalTraderAssistant.__init__` on empty data, multi-ticker input, NaN tickers, or bad weights.
- `DownloadError` — reserved for download-layer failures; not yet raised at call sites.

### Logging

All modules use `logging.getLogger(__name__)`. `wrappers.py` is the only module that configures handlers (three `FileHandler` instances writing to `logs/`). No other module configures handlers. The `_logger` in `processor.py` is defined at the top of the file, before all class bodies.

### Debugging guide

| Symptom | Where to look |
|---|---|
| Empty `composite_scores` DataFrame | `logs/error.log` — check for `evaluate() failed` or `compute_valuation_metrics failed` |
| `EvaluationError` on `FundamentalTraderAssistant` | `data` has empty/multi/NaN ticker, or `weights` has empty/multi/NaN sector |
| `SectorNotFoundError` | Ticker not in `financialtools/data/sector_ticker.txt`, or sector missing from benchmark Excel file |
| LLM returns unexpected output | `OutputFixingParser` is the recovery path — check `chains.py`; note `format_instructions` has no placeholder in the prompt (TODO in `chains.py`) |
| Logs written to wrong directory | Confirm `wrappers.py` is imported from the package, not copied — `_LOGS_DIR` is `__file__`-relative |
