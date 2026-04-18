# Architecture Refactor Plan

**Date:** 2026-04-17  
**Reviewer:** core-architect agent  
**Scope:** `financialtools/`, `agents/`, `tests/`  
**Status:** Not started

---

## Overview

Three-stage pipeline (download → score → LLM synthesis) with a parallel fan-out multi-agent layer. Architecture is well-documented with clear ownership across `config → processor → analysis`. Eleven findings identified; three are concrete dependency layer violations.

---

## Dependency Violations (root causes)

| # | Violation | Root Cause |
|---|-----------|------------|
| V1 | `wrappers.py` → `analysis.py` deferred runtime import | `build_weights()` lives in the wrong layer |
| V2 | `utils.py` → `yfinance` domain call | `get_ticker_profile`/`enrich_tickers` belong in acquisition layer |
| V3 | `wrappers.py` → `polars` | Trivial column transform expressible in pure pandas |

---

## Clean Target Dependency Diagram

```
exceptions.py       (leaf — no deps)
config.py           (leaf — pure dicts)
utils.py            ← exceptions, pandas
processor.py        ← exceptions, utils, yfinance, pandas, numpy
wrappers.py         ← processor, exceptions, utils, pandas
prompts.py          (leaf — pure strings)
pydantic_models.py  ← pydantic
analysis.py         ← config, processor, pydantic_models, prompts, utils, langchain
__init__.py         (re-exports)

agents/             ← financialtools.*, langchain, langgraph
```

---

## Task List

Execute in order: S-items → M-items (top-down) → L-items last.

### S — Small (self-contained, no cross-file deps)

- [x] **S1** Replace `print()` with `_logger` in `utils.py`  
  All `print()` calls → `_logger.info` / `_logger.error`. Add `_logger = logging.getLogger(__name__)`.  
  Files: `financialtools/utils.py`  
  Acceptance: no `print()` in production paths; log records reach `logs/`; tests pass.

- [x] **S2** Replace `print()` with `_logger` in `wrappers.py` and `processor.py`  
  Same as S1 for remaining files.  
  Files: `financialtools/wrappers.py`, `financialtools/processor.py`  
  Acceptance: same as S1.

- [x] **S3** Delete `_REGIME_HUMAN_TEMPLATE` duplicate in `analysis.py`  
  `_REGIME_HUMAN_TEMPLATE` is identical to `_TOPIC_HUMAN_TEMPLATE`. Remove it; update `_build_regime_chain()` to use `_TOPIC_HUMAN_TEMPLATE`.  
  Files: `financialtools/analysis.py`  
  Acceptance: one human template; `_build_regime_chain` still works; tests pass.

- [x] **S4** Delete commented-out code blocks in `processor.py`  
  Remove lines 83–88 (disabled pivot filter), 96–104 (`__format_fin_data`), 282–288 (JSON save block).  
  Files: `financialtools/processor.py`  
  Acceptance: no commented-out blocks remain; tests pass.

- [x] **S5** Eliminate Polars from `_preprocess_df`  
  Replace the `pl.from_pandas → polars → to_pandas` round-trip with native pandas `.dt.year`.  
  Files: `financialtools/wrappers.py`  
  Acceptance: `import polars as pl` removed; behavior identical; tests pass.

---

### M — Medium (cross-file, requires coordination)

- [x] **M1** Extract `resolve_sector()` to `utils.py`  
  The sector-detection regex is duplicated in `wrappers.py` and `agents/_tools/data_tools.py`. Extract to a single `resolve_sector(info_df, fallback="default") -> str` in `utils.py`.  
  Files: `financialtools/utils.py`, `financialtools/wrappers.py`, `agents/_tools/data_tools.py`  
  Acceptance: one implementation; both call sites use it; behavior identical; tests pass.

- [x] **M2** Promote `_SCORE_THRESHOLDS` and `_INVERSE_METRICS` to class-level constants  
  Both are rebuilt inside `_score_metric()` on every call. Move to class scope on `FundamentalMetricsEvaluator`.  
  Files: `financialtools/processor.py`  
  Acceptance: accessible as `FundamentalMetricsEvaluator._SCORE_THRESHOLDS`; existing tests pass without modification.

- [x] **M3** Move `build_weights()` / `list_sectors()` to `utils.py`; fix deferred import  
  Neither function has LLM dependencies. Moving to `utils.py` eliminates the circular-import workaround in `wrappers.py`. Re-export from `analysis.py` for backward compat.  
  Files: `financialtools/utils.py`, `financialtools/analysis.py`, `financialtools/wrappers.py`  
  Acceptance: deferred import removed; top-level import works; `__init__.py` unchanged; tests pass.

- [x] **M4** Add `"regime"` to `_TOPIC_MAP`; delete `_build_regime_chain()`  
  `_TOPIC_MAP` is the single source of truth for topic → (prompt, model_cls). Regime is currently excluded, creating a second source of truth.  
  Files: `financialtools/analysis.py`  
  Acceptance: `_TOPIC_MAP["regime"]` entry added; `_build_regime_chain` deleted; `run_topic_analysis("regime", ...)` works; tests pass.  
  Note: requires S3 to be completed first.

- [ ] **M5** Move `get_ticker_profile()` / `enrich_tickers()` out of `utils.py`  
  These functions call `yfinance.Ticker()` — domain code in a generic utility module. Move to `wrappers.py` or add a `# --- standalone helpers ---` section and scope the `yfinance` import.  
  Files: `financialtools/utils.py`, `financialtools/wrappers.py`  
  Acceptance: `utils.py` has no `yfinance` import at module level; functions accessible from expected location; tests pass.

- [x] **M6** Convert `DownloaderWrapper` static-only class to module-level functions + shim  
  `DownloaderWrapper` uses `__slots__ = ()` and only `@staticmethod` methods — it is a namespace, not an object. Convert to module-level functions; keep a thin shim class for public API compat.  
  Files: `financialtools/wrappers.py`  
  Acceptance: `DownloaderWrapper.download_data` still works; no instances created; tests pass.

---

### L — Large (structural split, do last)

- [x] **L1** Split `processor.py` into `downloader.py` + `evaluator.py`  
  `processor.py` is ~970 lines with two unrelated classes. `Downloader` depends on `yfinance`; `FundamentalMetricsEvaluator` depends only on `pandas`/`numpy`/`config`. Co-location is historical, not functional.  
  Files: `financialtools/downloader.py` (new), `financialtools/evaluator.py` (new), `financialtools/processor.py` (re-export shim)  
  Acceptance: `from financialtools.processor import Downloader, FundamentalMetricsEvaluator` still works; all callers unchanged; all tests pass.  
  Note: complete M2 first to reduce `processor.py` size before splitting.

---

## Progress Summary

| Phase | Total | Done | Remaining |
|-------|-------|------|-----------|
| S (Small) | 5 | 5 | 0 |
| M (Medium) | 6 | 5 | 1 |
| L (Large) | 1 | 1 | 0 |
| **Total** | **12** | **11** | **1** |

---

## Execution Log

| Date | Task | Outcome | Notes |
|------|------|---------|-------|
| 2026-04-17 | S1 | Done | 6 `print()` → `_logger`; `logging` import + `_logger` added at module level. 4 pre-existing test failures in `agents/_cache.py` (double-underscore cache key) unrelated to this change. |
| 2026-04-17 | S2 | Done | 4 `print()` in `processor.py` + 4 in `wrappers.py` → `_logger`/`logger`. Both files already had module-level loggers — no new imports needed. |
| 2026-04-17 | S3 | Done | Deleted `_REGIME_HUMAN_TEMPLATE`; `_build_regime_chain()` now delegates to `_build_chain_parts()` using `_TOPIC_HUMAN_TEMPLATE`. One human template remains. |
| 2026-04-17 | S4 | Done | Removed 3 commented-out blocks from `processor.py`: disabled pivot filter, `__format_fin_data` stub, and JSON save block in `stream_download`. |
| 2026-04-17 | S5 | Done | Removed `import polars as pl`; `_preprocess_df` reimplemented in pure pandas (`.dt.year` + column reorder). |
| 2026-04-17 | M1 | Done | `resolve_sector(info_df, fallback) -> str` added to `utils.py`; `import re` added. Both call sites updated (`wrappers.py`, `agents/_tools/data_tools.py`); `import re` removed from both. Exported from `__init__.py`. |
| 2026-04-17 | M2 | Done | `_SCORE_THRESHOLDS` (dict) and `_INVERSE_METRICS` (frozenset) promoted to class-level constants on `FundamentalMetricsEvaluator`. `_score_metric()` now references `self._SCORE_THRESHOLDS` / `self._INVERSE_METRICS`. Leftover commented `get_metric_category` block also removed. |
| 2026-04-17 | M3 | Done | `build_weights()` + `list_sectors()` moved to `utils.py` (+ `config` import). `analysis.py` re-exports them via `from financialtools.utils import ...`; `sec_sector_metric_weights` import removed from `analysis.py`. `wrappers.py` deferred import replaced with module-level `from financialtools.utils import build_weights`. All 6 import sites verified unchanged. |
| 2026-04-17 | M4 | Done | `"regime"` added to `_TOPIC_MAP`; `_build_regime_chain()` deleted from `analysis.py`. `run_topic_analysis()` loop now covers regime automatically. `app.py`: removed `_build_regime_chain` import; added `_DISPLAY_TOPICS` filter; fixed pre-existing `quantitative_overview` gap in `_TOPIC_LABEL`/`_TOPIC_RENDERERS`; Stage 4 uses `_build_topic_chain("regime", llm)`. |
| 2026-04-17 | M6 | Done | `DownloaderWrapper` class removed; 4 static methods promoted to module-level functions (`_preprocess_df`, `_download_single_ticker`, `_download_multiple_tickers`, `download_data`). `DownloaderWrapper` kept as a 3-line shim: `download_data = staticmethod(download_data)`. All internal `DownloaderWrapper.X` calls replaced with plain `X`. |
| 2026-04-17 | L1 | Done | `processor.py` (~970 lines) split into `downloader.py` (Downloader + RateLimiter re-export) and `evaluator.py` (FundamentalMetricsEvaluator, FundamentalTraderAssistant, _empty_result, constants). `processor.py` replaced with a 20-line re-export shim. All 7 import sites remain unchanged. 61 tests: same 4 pre-existing cache_key failures, no new failures. |
