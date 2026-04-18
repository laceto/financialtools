# Coding Rules

Load this file when: writing new code, adding metrics, modifying pipelines, or extending models.
Reference `architecture.md` for module map and data flows.

---

## Scoring Invariant

```
composite_score = sum(metric_score_i * weight_i) / sum(weight_i)
```
`metric_score_i ∈ {1, 2, 3, 4, 5}`. Higher is better.

**Which weights config to use:**
- `analysis.py` / `agents/` pipeline → `config.sec_sector_metric_weights` (yfinance sectorKey convention: lowercase, dashes — e.g. `"technology"`, `"financial-services"`)
- Legacy `chains.py` / direct `FundamentalTraderAssistant` calls → `config.sector_metric_weights` (title-case — e.g. `"Technology"`)

Fallback to `config.grouped_weights` if the sector key is not found (logged as WARNING).

### 24 Scored Metrics (produced by `compute_metrics()`)

*Original 11:* `GrossMargin, OperatingMargin, NetProfitMargin, EBITDAMargin, ROA, ROE, FCFToRevenue, FCFYield, FCFtoDebt, DebtToEquity, CurrentRatio`

*Extended 13:* `QuickRatio, CashRatio, WorkingCapitalRatio, DebtRatio, EquityRatio, NetDebtToEBITDA, InterestCoverage, ROIC, AssetTurnover, OCFRatio, FCFMargin, CashConversion, CapexRatio`

**Inverse scoring** (lower value → higher score): `DebtToEquity`, `DebtRatio`, `NetDebtToEBITDA`, `CapexRatio`. Declared as `_INVERSE_METRICS` inside `score_metric()`.

`SCORED_METRICS` constant is for reference only. `evaluate()` and `compute_scores()` derive `value_vars` **dynamically** from `compute_metrics()` output columns — adding a metric to `compute_metrics()` automatically includes it in scoring without touching `SCORED_METRICS`.

### 14 Unscored Extended Metrics (returned under `"extended_metrics"` key)

NOT fed into composite scores — time-differential (`pct_change`) or lack universal thresholds.

*Efficiency chain:* `ReceivablesTurnover, DSO, InventoryTurnover, DIO, PayablesTurnover, DPO, CCC`
*Growth:* `RevenueGrowth, NetIncomeGrowth, FCFGrowth`
*Red-flag ratios:* `Accruals, DebtGrowth, Dilution, CapexToDepreciation`

`compute_extended_metrics()` sorts a copy of `self.d` by `time` before `pct_change()` — `self.d` is never mutated.

---

## Key Conventions

- **Pydantic v2**: always `.model_dump()`, never `.dict()`
- **Tools always return JSON strings, never raise** — errors arrive as `{"error": "..."}`
- **No `OutputFixingParser`**: `analysis.py` uses a built-in one-shot fix retry in `_invoke_chain()`
- **`_EMPTY_RESULT_KEYS`** must contain `"extended_metrics"` — if you add a new key to `evaluate()` output, add it here too
- **`_TOPIC_MAP`** in `analysis.py` is the single source of truth for topic → `(prompt, model_cls)` — add new topics here only
- Shared metric descriptions live in `prompts.py` (`_FINANCIAL_METRICS_BLOCK`, `_EXTENDED_METRICS_BLOCK`, `_TOPIC_METRICS`) — do not duplicate metric definitions elsewhere
- `config.py` is the single source of truth for all scoring weights — do not hardcode weights elsewhere

## Exceptions

```python
from financialtools.exceptions import SectorNotFoundError, EvaluationError, DownloadError
```

- `EvaluationError` — raised by `FundamentalMetricsEvaluator.__init__` on empty data, multi-ticker input, NaN tickers, or bad weights. Also raised by `run_topic_analysis()` when download returns empty DataFrame.
- `SectorNotFoundError` — raised by `chains.get_stock_evaluation_report` if sector missing from benchmark files. Inherits `ValueError`.
- `DownloadError` — reserved for download-layer failures; not yet raised at call sites.

## Logging

All modules use `logging.getLogger(__name__)`. `wrappers.py` is the **only** module that configures handlers. Module-level `_logger` instances are defined at file top in `downloader.py` and `evaluator.py` (the implementation modules). Do not add handlers in other modules.

---

## When Done

→ Verify: does the change mutate `self.d` or `m_long`? If yes, use a copy instead.
→ Verify: if you added a key to `evaluate()` output, did you add it to `_EMPTY_RESULT_KEYS`?
→ Verify: new scored metric added to `compute_metrics()` — no need to touch `SCORED_METRICS`.
→ Run tests: `python -m unittest discover -s tests`
