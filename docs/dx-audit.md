# DX Audit — financialtools

_Generated: 2026-04-17_

## Summary

The library has solid layered architecture but ships several friction points a new user hits immediately. The three most damaging: two parallel sector-naming systems where one silently falls back to wrong weights; inconsistent failure return shapes between `download_data()` (returns `None`) and `evaluate_single()` (returns empty dict); and `FundamentalTraderAssistant` — the core class — named like a trading bot rather than an evaluator.

---

## Issues (13 found)

| # | Issue | Classification |
|---|---|---|
| 1 | Two sector-naming systems (`sector_metric_weights` vs `sec_sector_metric_weights`) — wrong key silently uses default weights | Medium |
| 2 | `download_data()` returns `None` on failure; `evaluate_single()` returns empty dict — callers need two different null checks | Breaking to fix |
| 3 | `FundamentalTraderAssistant` misleads — it's an evaluator/scorer, not a trading assistant | Breaking rename |
| 4 | `_empty_result()` crosses module boundary as a private import — the result shape contract should be public | Additive fix |
| 5 | `FundamentalEvaluator.__init__` requires callers to manually call `build_weights()` before constructing — always needed, should be encapsulated | Additive fix |
| 6 | `Downloader("AAPL")` constructs silently with all data as `None`; only `from_ticker()` is safe | Breaking guard |
| 7 | README Quick Start uses `sector="Technology"` — not a valid key, silently uses default weights | Docs |
| 8 | `export_financial_results()` / `read_financial_results()` missing from `__init__.py` — invisible to tab-complete | Additive |
| 9 | `stream_download` has no type annotations; `out_dir` default resolves relative to caller's cwd | Additive |
| 10 | `score_metric()` / `metrics_red_flags()` are public but only usable with internal long-format DataFrames | Should be private |
| 11 | `to_dict()` silently drops `evaluate_output` (DataFrames) with no docstring explanation | Docs |
| 12 | `agents/_tools/topic_tools.py` imports `_build_topic_chain` / `_invoke_chain` as private symbols across package boundary | Additive |
| 13 | `DownloaderWrapper` is a static-only class — no instance state, no reason to instantiate | Design debt |

---

## Issue Details

### Issue 1 — Two sector naming systems, no clear guidance on which to use

**Affected:** `config.sector_metric_weights`, `config.sec_sector_metric_weights`, `build_weights()`, `run_topic_analysis()`, `scripts/run_analysis.py`, `README.md`

`config.py` exports two sector weight dicts. `sector_metric_weights` uses Title Case ("Technology Services"). `sec_sector_metric_weights` uses yfinance sectorKey convention ("technology"). Both are visible exports. Calling `run_topic_analysis("AAPL", sector="Technology Services")` silently falls back to "default" weights — no error.

**Fix:**
1. Add valid keys to the `build_weights()` fallback warning (`analysis.py:219`)
2. Mark `sector_metric_weights` as LEGACY in docs
3. Fix CLAUDE.md example: `--sector "Technology Services"` → `--sector technology`

---

### Issue 2 — Inconsistent failure return shapes

**Affected:** `DownloaderWrapper.download_data()` (`wrappers.py:192`), `FundamentalEvaluator.evaluate_single()` (`wrappers.py:244`)

`download_data()` returns `None` on failure; `evaluate_single()` returns `_empty_result()` (a dict of empty DataFrames). Two different shapes for the same concept — "no usable output."

**Fix:** Change `download_data()` to raise `DownloadError` on total failure (consistent with `Downloader.from_ticker()`), or return an empty DataFrame to make the check uniform.

---

### Issue 3 — `FundamentalTraderAssistant` name misleads

**Affected:** `processor.py`, `__init__.py`, `README.md`, `wrappers.py`, `agents/_tools/data_tools.py`

The class computes fundamental metrics and scores — it is an evaluator. "Trader assistant" implies execution intent. `FundamentalEvaluator` (the wrapper) has the accurate name while the lower-level class does not.

**Fix:** Rename to `FundamentalMetricsEvaluator`. Add alias for one release, then remove old name.

---

### Issue 4 — `_empty_result()` is a private cross-module import

**Affected:** `processor.py:288`, `wrappers.py:8`

`wrappers.py` imports `_empty_result` from `processor.py` via a leading-underscore name. The empty result shape is a public contract (what `evaluate()` always returns) and should be exposed as such.

**Fix:** Expose `empty_evaluate_result()` from `__init__.py` as a public alias.

---

### Issue 5 — `FundamentalEvaluator.__init__` requires manual `build_weights()` call

**Affected:** `wrappers.py:226`, `analysis.py:205`

Users must always call `build_weights(sector)` before constructing `FundamentalEvaluator`. There is no other valid weights source. The two-step boilerplate serves no user need.

**Fix:** Add `sector` parameter to `FundamentalEvaluator.__init__`; call `build_weights()` internally when provided. Old `weights=` param stays for power users.

```python
# After
evaluator = FundamentalEvaluator(df=df, sector="technology")
```

---

### Issue 6 — `Downloader.__init__` leaves internals as `None` when called directly

**Affected:** `processor.py:23`, `processor.py:38`

`Downloader("AAPL")` produces an object with all financial data as `None`. `get_merged_data()` returns an empty DataFrame silently. Only `Downloader.from_ticker()` is safe.

**Fix:** Guard `__init__` with a sentinel parameter; raise `TypeError` with a clear message if called without going through `from_ticker`.

---

### Issue 7 — README Quick Start uses invalid sector value

**Affected:** `README.md` lines 24, 141

`sector="Technology"` is not a key in `sec_sector_metric_weights`. Valid key is `"technology"`. Silent fallback to default weights.

**Fix:** Change to `sector="technology"`. Add one-line note pointing to `list_sectors()`.

---

### Issue 8 — I/O helpers not exported from `__init__.py`

**Affected:** `wrappers.py:335,368`, `financialtools/__init__.py`

`export_financial_results()` and `read_financial_results()` are public functions but absent from `__all__` in `__init__.py`. Invisible to tab-complete and `from financialtools import *`.

**Fix:** Add both to `__init__.py` and `__all__`.

---

### Issue 9 — `stream_download` missing type annotations and relative `out_dir`

**Affected:** `processor.py:234`

No type hints on `tickers` or return type. `out_dir="financial_data"` resolves relative to the caller's cwd — writes to unexpected location from notebooks.

**Fix:** Annotate fully. Document the relative-path behaviour or default to a package-anchored directory.

---

### Issue 10 — `score_metric()` / `metrics_red_flags()` are public but only usable with internal data

**Affected:** `processor.py:558,759`

Both methods operate on an internally-structured long-format DataFrame that only exists after `compute_metrics()` + `melt()`. No external caller can use them correctly without replicating internal pipeline steps.

**Fix:** Mark both `_score_metric` / `_metrics_red_flags` (private). Add comment in `evaluate()` explaining they are internal pipeline steps.

---

### Issue 11 — `to_dict()` silently drops `evaluate_output`

**Affected:** `analysis.py:174`

`TopicAnalysisResult.to_dict()` serialises 9 of 11 fields. `evaluate_output` (raw DataFrames) is dropped without explanation. No docstring note.

**Fix:** One sentence in docstring: "Note: `evaluate_output` is excluded — contains pandas DataFrames which are not JSON-serialisable."

---

### Issue 12 — `agents/` imports private symbols from `financialtools`

**Affected:** `agents/_tools/topic_tools.py:50`

```python
from financialtools.analysis import _build_topic_chain, _invoke_chain
```

`agents/` is a separate package importing private symbols across a package boundary. Breaks encapsulation guarantees.

**Fix:** Promote `_build_topic_chain` / `_invoke_chain` to public and add to `__init__.py`.

---

### Issue 13 — `DownloaderWrapper` is a static-only class

**Affected:** `wrappers.py:64`

No `__init__`, no instance state, all `@staticmethod`. Constructing an instance is meaningless but silently allowed. The class is effectively a module namespace.

**Fix:** Add `__slots__ = ()` and class docstring "do not instantiate". Long-term: promote methods to module-level functions.

---

## Quick Wins

Ranked by DX impact ÷ effort:

1. **Fix sector in README lines 24/141** — `"Technology"` → `"technology"`. 2 min. Prevents every new user from silently getting wrong scores.
2. **Fix sector in CLAUDE.md line 13** — same problem from agent/contributor entry point. 1 min.
3. **Add valid sector list to `build_weights()` fallback warning** (`analysis.py:219`) — 1 line.
4. **Add `list_sectors()` public function** — 6 lines in `analysis.py`, 1 in `__init__.py`.
5. **Add `TopicAnalysisResult.failed_topics` property** — detect partial LLM failures without inspecting all 9 topic fields.
6. **Document `to_dict()` omission of `evaluate_output`** — one sentence.
7. **Add `export_financial_results` / `read_financial_results` to `__init__.py`** — 2 lines.
8. **Promote `_build_topic_chain` / `_invoke_chain` to public** — fixes cross-package private import.

---

## Proposed Improvements

- **`sector` param on `FundamentalEvaluator.__init__`** — accept `sector="technology"` directly.
- **`ConfigurationError(FinancialToolsError)`** in `exceptions.py` — replace bare `EnvironmentError` on missing API key.
- **Auto-detect sector in `run_topic_analysis()`** — agents already do this; the standalone function shouldn't require it.
- **`TopicAnalysisResult.failed_topics` property** — list of topic field names where LLM returned `None`.
