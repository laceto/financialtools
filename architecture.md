# Architecture Reference

## Overview

Fundamental stock analysis library — three pipeline stages:

1. **Data acquisition** — fetch and reshape Yahoo Finance data into long-format DataFrames
2. **Metric evaluation** — compute and score 24 financial metrics using sector-weighted rubrics, plus 14 unscored extended metrics
3. **LLM synthesis** — GPT-4.1-nano via LangChain → structured assessments (`StockRegimeAssessment`, seven topic models) wrapped in `TopicAnalysisResult`

Two LLM pipeline entry points:
- `chains.get_stock_evaluation_report()` — reads pre-computed Excel files in `financial_data/`
- `analysis.run_topic_analysis()` — self-contained, no Excel files needed; runs all 8 chains in one call

The Streamlit app (`app.py`) and CLI (`scripts/run_analysis.py`) both use `run_topic_analysis()`.

---

## Module Responsibilities

### Package (`financialtools/`)

| Module | Responsibility |
|---|---|
| `processor.py` | `RateLimiter` (thread-safe sliding-window), `Downloader` (yfinance fetch + wide→long reshape), `FundamentalTraderAssistant` (metric computation, 1-5 scoring, extended unscored metrics, red-flag detection) |
| `config.py` | Sector-specific metric weight dicts (`grouped_weights`, `sector_metric_weights`, `sec_sector_metric_weights`). Single source of truth for scoring weights. Three private baseline dicts (`_STD_EXT`, `_FIN_EXT`, `_RE_EXT`) DRY-up the 13 extended-metric keys. No I/O at import time — pure Python dicts. |
| `utils.py` | I/O helpers (`export_to_csv`, `export_to_xlsx`, `dataframe_to_json`, `flatten_weights`), yfinance profile helpers (`get_ticker_profile`, `enrich_tickers`) |
| `wrappers.py` | `DownloaderWrapper` (public download API, logs to `logs/`), `FundamentalEvaluator` (parallel evaluation via `ThreadPoolExecutor`), Excel export/read helpers |

### Repo root (not part of the installable package)

| File / Package | Responsibility |
|---|---|
| `chains.py` | LangChain pipeline: reads Excel results → invokes `gpt-4.1-nano` → returns `StockRegimeAssessment`. Uses `PydanticOutputParser` directly (no `OutputFixingParser`). |
| `tools.py` | `make_tools(base_dir)` factory — returns one `@tool` (`get_stock_regime_report`). `TOOLS = make_tools()` is the in-repo default. All tools return JSON strings, never raise. |
| `analysis.py` | `run_topic_analysis(ticker, sector, year, model)` — self-contained pipeline. Returns `TopicAnalysisResult`. `_TOPIC_MAP` is the single source of truth for topic → `(prompt, model_cls)` pairs. Uses `sec_sector_metric_weights` via `_build_weights()`. Built-in one-shot fix retry on parse error. |
| `pydantic_models.py` | `StockRegimeAssessment` (original, backward-compatible). Seven topic models: `LiquidityAssessment`, `SolvencyAssessment`, `ProfitabilityAssessment`, `EfficiencyAssessment`, `CashFlowAssessment`, `GrowthAssessment`, `RedFlagsAssessment`. `ComprehensiveStockAssessment` wraps all. All Pydantic v2; use `.model_dump()`. |
| `prompts.py` | Two factories: `build_prompt(...)` for `StockRegimeAssessment` variants; `build_topic_prompt(topic)` for seven topic models. Shared metric-definition blocks are the single source of truth for metric descriptions. |
| `exceptions.py` | `FinancialToolsError` (base), `DownloadError`, `EvaluationError`, `SectorNotFoundError` (also a `ValueError`) |
| `agents/` | LangGraph `StateGraph` — `create_financial_manager()` orchestrates 7 parallel topic subgraphs and compiles a hedge-fund long/short conviction report. See `agents/AGENTS.md`. Key files: `graph_state.py` (`AnalysisState`), `graph_nodes.py` (node functions), `financial_agent.py` (graph factory), `_tools/data_tools.py` (`prepare_financial_data`), `_tools/topic_tools.py` (7 topic tools), `_cache.py` (disk cache). |

---

## Key Data Flows

**Download:**
```
Ticker → Downloader.from_ticker() → yfinance
  → balance_sheet / income_stmt / cashflow (wide → long via __reshape_fin_data)
  → get_merged_data() → merged financial DataFrame
      + broadcasts _MARKET_COLS (marketcap, currentprice, sharesoutstanding)
        from _info across all time periods (columns lowercased to snake_case)
  → DownloaderWrapper.download_data() → saves to logs/, returns pandas DataFrame
```

**Evaluate:**
```
merged_df + weights → FundamentalTraderAssistant(data, weights)  # raises EvaluationError on bad input
  → evaluate()
      → compute_metrics()              # produces 24 scored metric columns + sector
      → compute_valuation_metrics()    # P/E, P/B, P/FCF, EarningsYield → self.eval_metrics
      → raw_red_flags()                # cash-flow red flags
      → melt(value_vars=<dynamic>) → m_long
      → score_metric(m_long)           # 1–5 per metric (returns copy — does not mutate input)
      → merge(self.weights)            # adds sector + weights columns; warns on NaN weights
      → _compute_composite_scores()    # → self.scores (wide: sector, ticker, time, composite_score)
      → metrics_red_flags(m_long)      # → self.red_flags (returns copy — does not mutate input)
      → compute_extended_metrics()     # 14 unscored metrics
      → returns dict: metrics, eval_metrics, composite_scores, raw_red_flags, red_flags, extended_metrics
      → on any failure: returns _empty_result() (all keys, empty DataFrames) + logs error
```

**Score attribute schema — do not conflate:**
- `self.metric_scores` — long format, set by `compute_scores()`: ticker, time, metrics, value, score, sector
- `self.scores` — wide format, set by `evaluate()`: sector, ticker, time, composite_score

**Topic analysis (self-contained):**
```
run_topic_analysis(ticker, sector, year?, model?) → TopicAnalysisResult
  → Downloader.from_ticker(ticker).get_merged_data()   # raises EvaluationError if empty
  → _build_weights(sector)                             # falls back to "Default" with warning
  → FundamentalTraderAssistant(merged, weights).evaluate()
  → _normalise_time() + _filter_year() per DataFrame
  → dataframe_to_json() × 5
  → for topic in _TOPIC_MAP:
      _invoke_chain(...) → topic assessment | None  [one fix retry on parse failure]
  → _build_regime_chain(llm) → regime assessment | None
  → TopicAnalysisResult(ticker, sector, year, liquidity, solvency, …, regime, evaluate_output)
```

**Single-tool agent (tools.py):**
```
TOOLS = make_tools()   # base_dir="financial_data"
create_agent(model=llm, tools=tools, checkpointer=MemorySaver())
  → get_stock_regime_report(ticker, sector, year?) → JSON (model_dump())
```
All tools return JSON strings, never raise; errors arrive as `{"error": "..."}`.

**Multi-agent workflow (agents/):**
```
create_financial_manager(model, checkpointer) → CompiledStateGraph

agent.invoke({"ticker": "AAPL", "year": 2023}, config=...)
  → set_model node          → injects model into AnalysisState
  → prepare_data_node       → prepare_financial_data(ticker, sector?, year?)
      → Downloader + FundamentalTraderAssistant.evaluate()
      → auto-detects sector from get_info_data()["sector"] (sec_sector_metric_weights convention)
      → auto-detects company_name from get_info_data()["longName"]
      → writes agents/.cache/{KEY}/payloads.json
      → state ← {cache_key, company_name, resolved_sector}
  → 7 topic subgraphs (parallel fan-out)
      each: run_{topic}_analysis(cache_key) → state["{topic}_result"]
  → compile_report_node     → LLM synthesis → state["final_report"]
      → LONG/SHORT recommendation + per-topic deep-dives with metric values
```
State schema: `AnalysisState` in `agents/graph_state.py` — all keys use `Annotated[T, _last]` reducer to support parallel fan-in without `InvalidUpdateError`.

---

## Runtime Data Directories (not in repo)

- `financial_data/` — Excel outputs from `export_financial_results()` (required by `chains.py`)
- `logs/` — `info.log`, `error.log`, `debug.log` written by `DownloaderWrapper`. Path anchored to `os.path.dirname(__file__)/../logs` — independent of caller's cwd.

## Environment

Requires `.env` with `OPENAI_API_KEY` (loaded via `python-dotenv` in `chains.py`).
