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

# Streamlit app (single-ticker topic analysis UI)
streamlit run app.py

# CLI: single-ticker topic analysis
python scripts/run_analysis.py --ticker AAPL --sector "Technology Services"
python scripts/run_analysis.py --list-sectors
```

No Makefile, no dedicated lint/format tooling is configured. Add `ruff` or `black` if needed.

## Architecture

This is a **fundamental stock analysis library** that pipelines three concerns:

1. **Data acquisition** — fetch and reshape Yahoo Finance data into long-format DataFrames
2. **Metric evaluation** — compute and score 24 financial metrics using sector-weighted rubrics, plus 14 unscored extended metrics
3. **LLM synthesis** — send scored results to GPT-4.1-nano via LangChain and return structured assessments: `StockRegimeAssessment` (overall regime + valuation) and seven topic-focused models (`LiquidityAssessment` … `RedFlagsAssessment`) wrapped in `TopicAnalysisResult`

There are two LLM pipeline entry points:
- `chains.get_stock_evaluation_report()` — reads from pre-computed Excel files in `financial_data/`
- `analysis.run_topic_analysis()` — self-contained, no Excel files needed; runs all 8 chains in one call

The Streamlit app (`app.py`) and CLI (`scripts/run_analysis.py`) both use `run_topic_analysis()`.

### Module responsibilities

| Module | Responsibility |
|---|---|
| `processor.py` | `RateLimiter` (thread-safe sliding-window), `Downloader` (yfinance fetch + wide→long reshape), `FundamentalTraderAssistant` (metric computation, 1-5 scoring, extended unscored metrics, red-flag detection) |
| `config.py` | Sector-specific metric weight dicts (`grouped_weights`, `sector_metric_weights`, `sec_sector_metric_weights`). Single source of truth for all scoring weights. Three private baseline dicts (`_STD_EXT`, `_FIN_EXT`, `_RE_EXT`) DRY-up the 13 new extended-metric keys across all sector entries. No I/O at import time — pure Python dicts. |
| `utils.py` | I/O helpers (Excel/CSV), ticker/sector lookups (`get_sector_for_ticker`, `get_market_metrics`), DataFrame→JSON conversion, `get_fin_data`, `list_evaluated_tickers` |
| `tools.py` | `make_tools(base_dir, sector_file)` factory — returns five `@tool` functions with file paths baked in. `TOOLS = make_tools()` is the in-repo default. External consumers call `make_tools(base_dir=..., sector_file=...)` at bootstrap time. All tools return JSON strings, never raise; errors arrive as `{"error": "..."}`. |
| `wrappers.py` | `DownloaderWrapper` (public download API, logs to `logs/`), `FundamentalEvaluator` (parallel evaluation via `ThreadPoolExecutor`), Excel export/read helpers |
| `chains.py` | LangChain pipeline: reads Excel results → loads sector benchmarks → invokes `gpt-4.1-nano` → returns `StockRegimeAssessment`. Uses `PydanticOutputParser` directly (no `OutputFixingParser` — removed in LangChain 1.0). |
| `analysis.py` | `run_topic_analysis(ticker, sector, year, model)` — self-contained pipeline: download → evaluate → 8 LLM chains (7 topic models + `StockRegimeAssessment`). Returns `TopicAnalysisResult` dataclass. `_TOPIC_MAP` is the single source of truth for topic → `(prompt, model_cls)` pairs. Built-in one-shot fix retry on parse error (replaces `OutputFixingParser`). |
| `pydantic_models.py` | `StockRegimeAssessment` (regime + valuation — original, backward-compatible). Seven topic-focused models: `LiquidityAssessment`, `SolvencyAssessment`, `ProfitabilityAssessment`, `EfficiencyAssessment`, `CashFlowAssessment`, `GrowthAssessment`, `RedFlagsAssessment`. `ComprehensiveStockAssessment` wraps all seven plus top-level regime + evaluation fields. All Pydantic v2; use `.model_dump()`. |
| `prompts.py` | Two factories: `build_prompt(sector_aware, include_red_flags, include_extended_metrics)` for `StockRegimeAssessment` variants; `build_topic_prompt(topic)` for the seven topic models and `ComprehensiveStockAssessment`. Shared metric-definition blocks (`_FINANCIAL_METRICS_BLOCK`, `_EXTENDED_METRICS_BLOCK`, `_TOPIC_METRICS`) are the single source of truth for metric descriptions. Exports 5 regime prompt constants + 8 topic prompt constants. |
| `exceptions.py` | `FinancialToolsError` (base), `DownloadError`, `EvaluationError`, `SectorNotFoundError` (also a `ValueError`) |

### Key data flows

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
      → melt(value_vars=<dynamic: all non-id cols from compute_metrics()>) → m_long
      → score_metric(m_long)           # 1–5 per metric (returns copy — does not mutate input)
      → merge(self.weights)            # adds sector + weights columns; warns on NaN weights
      → _compute_composite_scores()    # → self.scores (wide: sector, ticker, time, composite_score)
      → metrics_red_flags(m_long)      # → self.red_flags (returns copy — does not mutate input)
      → compute_extended_metrics()     # 14 unscored metrics (efficiency chain, growth, red-flag ratios)
      → returns dict with keys: metrics, eval_metrics, composite_scores, raw_red_flags, red_flags, extended_metrics
      → on any failure: returns _empty_result() (all keys, fresh empty DataFrames) + logs error
  → compute_scores()            # standalone: melt(dynamic cols) → score_metric → self.metric_scores
                                #   (long format, one row per ticker/time/metric — NOT self.scores)
  → export_financial_results()  → financial_data/*.xlsx
```

**Score attribute schema — do not conflate:**
- `self.metric_scores` — long format, set by `compute_scores()`, columns: ticker, time, metrics, value, score, sector
- `self.scores` — wide format, set by `evaluate()`, columns: sector, ticker, time, composite_score

**LLM report (from Excel files):**
```
get_stock_evaluation_report(ticker, year?, base_dir, sector_file)
  → read_financial_results() from base_dir/*.xlsx
  → get_sector_for_ticker(ticker, sector_file=sector_file) + get_market_metrics()
  → LangChain: ChatPromptTemplate | ChatOpenAI | PydanticOutputParser
  → StockRegimeAssessment (regime, evaluation, rationale, market_comparison)
```

**Topic analysis (self-contained, no Excel required):**
```
run_topic_analysis(ticker, sector, year?, model?) → TopicAnalysisResult
  → Downloader.from_ticker(ticker).get_merged_data()   # raises EvaluationError if empty
  → _build_weights(sector)                             # falls back to "Default" with warning
  → FundamentalTraderAssistant(merged, weights).evaluate()
  → _normalise_time() + _filter_year() per DataFrame
  → dataframe_to_json() × 5  (metrics, extended_metrics, eval_metrics, composite_scores, red_flags)
  → for topic in _TOPIC_MAP:
      _build_topic_chain(topic, llm) → (prompt, PydanticOutputParser)
      _invoke_chain(prompt, parser, llm, payloads, ...) → topic assessment | None
          primary: prompt | llm → parser.invoke(raw)
          on failure: _FIX_PROMPT | llm → parser.invoke(fixed_raw)  [one retry]
  → _build_regime_chain(llm) → regime assessment | None
  → TopicAnalysisResult(ticker, sector, year, liquidity, solvency, …, regime, evaluate_output)
```

**Agent (tools.py):**
```
# In-repo default:
TOOLS = make_tools()   # base_dir="financial_data", sector_file="financialtools/data/sector_ticker.txt"

# External consumer — paths baked in at bootstrap, never exposed to the LLM:
tools = make_tools(base_dir="/path/to/data", sector_file="/path/to/sector_ticker.txt")

create_agent(model=llm, tools=tools, checkpointer=MemorySaver())
  list_available_tickers()       → list_evaluated_tickers(base_dir) → JSON array
  get_stock_metrics(ticker,year) → get_fin_data(base_dir)           → JSON {metrics, composite_scores, red_flags}
  get_sector_benchmarks(sector)  → get_market_metrics(base_dir) ×2  → JSON {financial, valuation}
  get_red_flags(ticker)          → get_fin_data(base_dir)           → JSON {red_flags}
  get_stock_regime_report(t,yr)  → get_stock_evaluation_report(base_dir, sector_file) → JSON (model_dump())
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

**24 scored metrics** are the columns produced by `compute_metrics()`:

*Original 11:* `GrossMargin, OperatingMargin, NetProfitMargin, EBITDAMargin, ROA, ROE, FCFToRevenue, FCFYield, FCFtoDebt, DebtToEquity, CurrentRatio`

*Extended 13:* `QuickRatio, CashRatio, WorkingCapitalRatio, DebtRatio, EquityRatio, NetDebtToEBITDA, InterestCoverage, ROIC, AssetTurnover, OCFRatio, FCFMargin, CashConversion, CapexRatio`

Four of these use **inverse scoring** (lower value → higher score): `DebtToEquity`, `DebtRatio`, `NetDebtToEBITDA`, `CapexRatio`. The set is declared as `_INVERSE_METRICS` inside `score_metric()`.

`SCORED_METRICS` (module-level constant in `processor.py`) lists all 24 names for reference, but `evaluate()` and `compute_scores()` derive `value_vars` dynamically from `compute_metrics()` output columns — adding a metric to `compute_metrics()` automatically includes it in scoring without touching `SCORED_METRICS`.

**14 unscored extended metrics** are computed by `compute_extended_metrics()` and returned under the `"extended_metrics"` key. They are NOT fed into the composite score because they are time-differential (`pct_change`) or derived chains that lack universal thresholds:

*Efficiency chain:* `ReceivablesTurnover, DSO, InventoryTurnover, DIO, PayablesTurnover, DPO, CCC`
*Growth:* `RevenueGrowth, NetIncomeGrowth, FCFGrowth`
*Red-flag ratios:* `Accruals, DebtGrowth, Dilution, CapexToDepreciation`

`compute_extended_metrics()` sorts a copy of `self.d` by `time` before calling `pct_change()` — `self.d` is never mutated.

### Exceptions

```python
from financialtools.exceptions import SectorNotFoundError, EvaluationError, DownloadError
```

- `SectorNotFoundError` — raised by `get_sector_for_ticker`, `get_market_metrics`. Inherits `ValueError` so `except ValueError` blocks still work.
- `EvaluationError` — raised by `FundamentalTraderAssistant.__init__` on empty data, multi-ticker input, NaN tickers, or bad weights. Also raised by `run_topic_analysis()` when the download returns an empty DataFrame.
- `DownloadError` — reserved for download-layer failures; not yet raised at call sites.

### Logging

All modules use `logging.getLogger(__name__)`. `wrappers.py` is the only module that configures handlers (three `FileHandler` instances writing to `logs/`). No other module configures handlers. The `_logger` in `processor.py` is defined at the top of the file, before all class bodies.

### Debugging guide

| Symptom | Where to look |
|---|---|
| Empty `composite_scores` DataFrame | `logs/error.log` — check for `evaluate() failed` or `compute_valuation_metrics failed` |
| `EvaluationError` on `FundamentalTraderAssistant` | `data` has empty/multi/NaN ticker, or `weights` has empty/multi/NaN sector |
| `SectorNotFoundError` | Ticker not in `financialtools/data/sector_ticker.txt`, or sector missing from benchmark Excel file |
| New extended-metric columns all NaN | Optional source column absent for that ticker (e.g. `inventory`, `invested_capital`, `ebit`); logged as warning — not an error |
| `extended_metrics` key missing from `evaluate()` result | `_EMPTY_RESULT_KEYS` was not updated — must contain `"extended_metrics"` |
| Growth rates in wrong order | `compute_extended_metrics()` sorts by `time` before `pct_change()` — check whether input `time` values are parseable strings or timestamps |
| LLM returns unexpected output in `chains.py` | `PydanticOutputParser` is used directly; no auto-fix. Check raw LLM response in `logs/debug.log`. Note `format_instructions` placeholder is present but prompt may not surface schema to the LLM. |
| LLM topic chain returns `None` in `TopicAnalysisResult` | `_invoke_chain` logs a WARNING with the topic name — check logs. One fix retry is attempted automatically. If both fail, the field is `None` and the run continues. |
| Logs written to wrong directory | Confirm `wrappers.py` is imported from the package, not copied — `_LOGS_DIR` is `__file__`-relative |
