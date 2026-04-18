# Debugging Rules

Load this file when: diagnosing failures, tracing unexpected output, or investigating NaN/empty results.

---

## Log Files

| File | Content |
|---|---|
| `logs/error.log` | Caught exceptions, `evaluate() failed`, evaluation errors |
| `logs/info.log` | Download/evaluation lifecycle events |
| `logs/debug.log` | Raw LLM responses from `chains.py` |

Log path is anchored to `wrappers.py`'s `__file__` — if logs appear in the wrong directory, confirm `wrappers.py` is imported from the installed package, not a copied file.

---

## Symptom → Cause → Fix

| Symptom | Cause | Where to look / fix |
|---|---|---|
| Empty `composite_scores` DataFrame | `evaluate()` failed silently | `logs/error.log` — search `evaluate() failed` or `compute_valuation_metrics failed` |
| `EvaluationError` on `FundamentalMetricsEvaluator` | `data` has empty/multi/NaN ticker, or `weights` has empty/multi/NaN sector | Inspect input DataFrame before constructing `FundamentalMetricsEvaluator` |
| `SectorNotFoundError` | Sector missing from benchmark Excel | Check `financial_data/metrics_by_sectors.xlsx` |
| Extended-metric columns all NaN | Optional source column absent for ticker (e.g. `inventory`, `invested_capital`, `ebit`) | Logged as WARNING, not error — expected for some tickers |
| `"extended_metrics"` key missing from `evaluate()` result | `_EMPTY_RESULT_KEYS` not updated | Add `"extended_metrics"` to `_EMPTY_RESULT_KEYS` in `evaluator.py` |
| Growth rates in wrong order | `time` column not sortable | `compute_extended_metrics()` sorts by `time` before `pct_change()` — verify `time` values are parseable strings or timestamps |
| LLM returns unexpected output in `chains.py` | `PydanticOutputParser` used directly, no auto-fix | Check raw LLM response in `logs/debug.log` |
| `TopicAnalysisResult` field is `None` | Both primary parse and fix-retry failed in `_invoke_chain` | `logs/` — search WARNING for the topic name. Field is `None` and run continues — not fatal |
| `ModuleNotFoundError: langchain.output_parsers` | `OutputFixingParser` removed — use `PydanticOutputParser` directly | `from langchain_core.output_parsers import PydanticOutputParser`; retry logic is in `_invoke_chain()` |
| Sector scores use `"default"` weights unexpectedly | `resolve_sector()` received multi-row `info_df`; `.to_string()` produced newline string that didn't match any key — **fixed 2026-04-18** | Check `logs/` for warning `"Sector '...' not found"` containing `\n` in the sector value |
| `enrich_tickers()` raises `ValueError: No objects to concatenate` | All `get_ticker_profile()` calls failed; `pd.concat([])` crashed — **fixed 2026-04-18** | Check `logs/error.log` for per-ticker errors; function now returns empty DataFrame instead of crashing |
| `run_topic_analysis` raises `ValueError` when serialising metrics | `dataframe_to_json` choked on NaN/Inf values present in metrics for banks or foreign tickers — **fixed 2026-04-18** | `logs/error.log`; metrics DataFrame contains NaN — expected for tickers with missing columns |
| `company_name` column contains `\n` in output data | `_download_single_ticker` used `.to_string()` on multi-row `longName` column — **fixed 2026-04-18** | Rebuild affected rows; check if `get_info_data()` returns more than one row for the ticker |

---

## Process

1. Identify symptom in the table above.
2. Check `logs/error.log` first (most failures surface here).
3. If LLM-related: check `logs/debug.log` for raw model output.
4. If data-related: inspect the DataFrame at the failing step — print shape, dtypes, and `.head()`.
5. Fix the minimal path; do not refactor while debugging.

---

## When Done

→ If you found a new failure mode not in the table above, add it.
→ If the fix required a code change → switch to coding-rules.md.
