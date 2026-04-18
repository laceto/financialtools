# Code Review Report — `financialtools`

**Branch:** `chore/code-review`
**Date:** 2026-04-16
**Reviewers:** Devil's Advocate · API & DX · Architecture & Code Quality · Performance & Reliability

---

## Fix Status

| Issue | Status | Commit ref |
|---|---|---|
| C1 — RateLimiter holds lock during sleep | ✅ Fixed | `processor.py:acquire()` |
| C2 — FundamentalEvaluator passes dict as weights | ✅ Fixed | `wrappers.py:FundamentalEvaluator.__init__` |
| S1 — `_invoke_chain` retry logic bug | ✅ Fixed | `analysis.py:_invoke_chain` |
| S2 — `evaluate()` swallows failures silently | ✅ Fixed | `processor.py:evaluate()` |
| S3 — `merge_results` crashes on None results | ✅ Fixed | `wrappers.py:233` |
| S4 — `from_ticker()` swallows all exceptions | ✅ Fixed | `processor.py:from_ticker` |
| S5 — Private helpers imported cross-package | ✅ Fixed | `analysis.py:build_weights` |
| S6 — No cache invalidation | ✅ Fixed | `_cache.py:clear_cache` |
| M1–M10 | ✅ Fixed | various |

---

## Executive Summary

1. ~~One **critical correctness bug**: `RateLimiter` holds its lock during `sleep()`, serialising all threads.~~ **Fixed.**
2. ~~One **blocking API bug**: `FundamentalEvaluator` passes a raw `dict` where `FundamentalTraderAssistant` expects a `pd.DataFrame`.~~ **Fixed.**
3. ~~The **retry logic in `_invoke_chain`** makes 3 LLM calls on a parse error instead of 2, and fixes the wrong output.~~ **Fixed.**
4. ~~**Silent `_empty_result()` on `evaluate()` failure** propagates empty DataFrames to the LLM unchecked, producing hallucinated assessments.~~ **Fixed.**
5. ~~The **public API surface is empty** — `__init__.py` exports nothing; two dead config dicts inflate `config.py` by ~170 lines.~~ **Fixed (M1, M3).**

Overall the codebase is well-structured at the macro level — the 3-stage pipeline is clear, invariants are documented, and the agent layer cleanly separates from the library. The issues are concentrated in error-handling contracts and a few sharp edges in the threading and retry layers.

---

## Critical Issues (must fix before merge)

### ✅ C1 — `RateLimiter` blocks all threads during sleep
**File:** `financialtools/processor.py:48`
**Owner:** Performance & Reliability
**Resolution:** `while True` moved outside `with self._lock:`. Lock is now held only during the window-check and the atomic `self.calls.append` on success. `sleep()` runs with the lock released so other threads can concurrently check their own rate windows. `break` replaced with `return` to eliminate the post-loop append that was outside the lock.

### ✅ C2 — `FundamentalEvaluator` passes `dict` where `pd.DataFrame` is required
**File:** `financialtools/wrappers.py:177`
**Owner:** API & DX
**Resolution:** `weights: dict` annotation changed to `weights: pd.DataFrame`. Docstring updated to specify the required schema (`sector`, `metrics`, `weights` columns) and reference `_build_weights(sector)` as the canonical constructor. No logic change needed — `self.weights` was already passed through unchanged.

---

## Significant Issues (should fix soon)

### ✅ S1 — `_invoke_chain` retry is a logic bug (3 LLM calls, wrong input to fixer)
**File:** `financialtools/analysis.py:326`
**Owner:** Devil's Advocate / Performance & Reliability
**Resolution:** `raw = raw_chain.invoke(inputs)` moved outside the `try` block so the response is in scope for the `except`. On parse failure, `broken_content` is captured from that original `raw` before the fix chain runs. The spurious second `raw_chain.invoke(inputs)` call inside the retry path was deleted. Call budget: 1 (happy path) / 2 (parse error).

### ✅ S2 — `evaluate()` swallows all exceptions and returns empty DataFrames
**File:** `financialtools/processor.py:evaluate()`
**Owner:** Devil's Advocate
**Resolution:** Two changes: (1) the `if m.empty` guard now raises `EvaluationError` instead of returning `_empty_result()`; (2) the outer `except Exception` now re-raises unexpected errors as `EvaluationError` (with `from e` chaining) instead of returning `_empty_result()`. A `except EvaluationError: raise` guard prevents double-wrapping. Callers that need soft failure (`FundamentalEvaluator.evaluate_single`, `scripts/run_pipeline.py`) already catch the exception — no changes needed there.

### ✅ S3 — `FundamentalEvaluator.evaluate_multiple` stores `None` for failed tickers; `merge_results` crashes on it
**File:** `financialtools/wrappers.py:233–235`, `wrappers.py:256`
**Owner:** Performance & Reliability
**Resolution:** Two changes: (1) `evaluate_multiple` now stores `_empty_result()` instead of `None` on parallel failure, and `print()` replaced with `logger.error(..., exc_info=True)`; (2) `merge_results` list comprehension rewritten to guard with `isinstance(result, dict)` and `isinstance(df, pd.DataFrame)` before calling `.empty` — eliminates the `AttributeError` on any non-dict entry that might slip through in future.

### ✅ S4 — `Downloader.from_ticker()` swallows exceptions and returns a silent empty object
**File:** `financialtools/processor.py:from_ticker`
**Owner:** Performance & Reliability
**Resolution:** The `except Exception` block that returned `cls(ticker)` — an empty `Downloader` with all `None` internals — now raises `DownloadError(f"[{ticker}] download failed: {e}") from e` instead. `DownloadError` was added to the import from `financialtools.exceptions`. Docstring updated with explicit `Raises` section explaining the old silent-failure behaviour and why it was dangerous. `data_tools.py` docstrings updated to reflect that `DownloadError` is the primary download failure signal; `prepare_financial_data` already catches it via the broad `except Exception` handler — no logic change needed there.

### ✅ S5 — `agents/data_tools.py` imports private helpers from `financialtools.analysis`
**File:** `agents/_tools/data_tools.py:38–42`
**Owner:** Architecture & Code Quality
**Resolution:** `_build_weights`, `_filter_year`, `_normalise_time` renamed to `build_weights`, `filter_year`, `normalise_time` in `analysis.py` (definitions + all internal call-sites). Section header comment updated from "Internal helpers" to "Public helpers". All call-sites updated across `agents/_tools/data_tools.py`, `app.py`, and `scripts/run_pipeline.py`. `run_pipeline.py` had a duplicate local `_build_weights` implementation — the duplicate was removed and replaced with the canonical import from `financialtools.analysis`. `wrappers.py` docstring reference updated. All three helpers (plus `run_topic_analysis`) added to `financialtools/__init__.py` which now establishes a real public API contract.

### ✅ S6 — No cache invalidation in `agents/_cache.py`
**File:** `agents/_cache.py`
**Owner:** Performance & Reliability
**Resolution:** Four-site change:
1. **`_cache.py`** — added `clear_cache(key)` to the public API. Uses `shutil.rmtree` to delete the entire `_CACHE_ROOT/{key}/` directory (payloads.json + all `{topic}.json` files from prior runs). No-op if the directory doesn't exist. Added `import shutil`, `import logging`, and module-level `_logger`.
2. **`data_tools._download_and_evaluate`** — added `force_refresh: bool = False` parameter. When `True`, calls `clear_cache(cache_key(ticker, year))` before Stage 1 download, ensuring the directory is fully wiped before new data lands. Log line updated to include `force_refresh=` flag.
3. **`data_tools.prepare_financial_data`** — `force_refresh` threaded through the `@tool` signature so the LLM-facing surface and CLI callers can request a refresh explicitly.
4. **`graph_state.AnalysisState`** + **`graph_nodes.prepare_data_node`** — `force_refresh: Annotated[Optional[bool], _last]` added to `AnalysisState` as a caller-supplied input; `prepare_data_node` reads it and passes `bool(state.get("force_refresh", False))` to `_download_and_evaluate`.

Usage: `agent.invoke({"ticker": "AAPL", "year": 2023, "force_refresh": True}, config=config)`

---

## Minor Issues and Suggestions

### ✅ M1 — `sector_metric_weights` and `grouped_weights` in `config.py` appear unused
**File:** `financialtools/config.py:30–202`
**Owner:** Architecture & Code Quality
**Resolution:** Both dicts retained (confirmed not in active pipeline code — no live imports found) and each annotated with a multi-line comment block explaining their purpose and status: `grouped_weights` is a legacy human-readable display structure (grouped by category label, title-case) used in notebooks; `sector_metric_weights` is the legacy title-case sector dict for `chains.py` backward compatibility, superseded by `sec_sector_metric_weights` (yfinance sectorKey convention) for all active code paths.

### ✅ M2 — `chains.py` is likely legacy with no deprecation marker
**File:** `chains.py`
**Owner:** Devil's Advocate / Architecture
**Resolution:** Added a 12-line deprecation block at the top of `chains.py` with: (1) a `# DEPRECATED` heading, (2) explanation of the Excel-file dependency, (3) a side-by-side migration guide (`chains.get_stock_evaluation_report` → `run_topic_analysis`), (4) a pointer to `financialtools/analysis.py`. Also added the M8 `OPENAI_API_KEY` guard here (see M8).

### ✅ M3 — `__init__.py` exports nothing
**File:** `financialtools/__init__.py`
**Owner:** API & DX
**Resolution:** `__init__.py` now exports the full public API surface via `__all__`: `Downloader`, `FundamentalTraderAssistant`, `DownloaderWrapper`, `FundamentalEvaluator`, `run_topic_analysis`, `build_weights`, `filter_year`, `normalise_time`, `merge_results`, `RateLimiter`, `DownloadError`, `EvaluationError`, `SectorNotFoundError`. The three analysis helpers were added as part of S5; `RateLimiter` added as part of M9; `merge_results` added here.

### ✅ M4 — `architecture.md` incorrectly lists package files as "repo root"
**File:** `architecture.md` module table
**Owner:** Architecture & Code Quality
**Resolution:** `analysis.py`, `pydantic_models.py`, `prompts.py`, `exceptions.py` moved from the "Repo root" table into the "Package (`financialtools/`)" table with updated descriptions. `chains.py` entry updated to show its deprecated status. `agents/` entry updated (8 subgraphs, `clear_cache` invalidation). `processor.py` and `utils.py` entries updated to reflect `RateLimiter` move (M9). Stale `_build_weights()` / `_normalise_time()` / `_filter_year()` references in data flow updated to public names (S5).

### ✅ M5 — `wrappers.py` configures file handlers at module import time
**File:** `financialtools/wrappers.py:22–46`
**Owner:** Architecture & Code Quality
**Resolution:** Module-level `FileHandler` creation and `os.makedirs` replaced with a `_configure_logging()` function guarded by a `_handlers_configured: bool` flag. Logger instance is still created at import time (cheap, no I/O). File handlers are attached only when `_configure_logging()` is called for the first time, which happens at the top of `_download_single_ticker` (and at the top of `_download_multiple_tickers`). Tests that import `DownloaderWrapper` without downloading any data no longer create `logs/` or open file handles.

### ✅ M6 — `SCORED_METRICS` list is documentation, not enforcement
**File:** `financialtools/processor.py:338–365`
**Owner:** Architecture & Code Quality
**Resolution:** Added `TestScoredMetricsEnforcement` test class to `tests/test_processor.py`. The test calls `compute_metrics()` on a synthetic DataFrame, derives the actual metric columns dynamically (excluding `ticker`, `time`, `sector`), and asserts `set(SCORED_METRICS) == actual_metric_cols` with a diagnostic diff message. This is a live enforcement test — unlike the existing `test_scored_metrics_constant_matches` which compares two static lists, this test catches drift between the constant and the implementation.

### ✅ M7 — `_download_multiple_tickers` is sequential, not parallel
**File:** `financialtools/wrappers.py:127–140`
**Owner:** API & DX
**Resolution:** Replaced the sequential `for ticker in tickers` loop with a `ThreadPoolExecutor` + `as_completed` pattern, matching the approach already used by `FundamentalEvaluator.evaluate_multiple`. Added `max_workers: int = 4` parameter (default conservative to respect yfinance rate limits — each worker has a 2-second sleep). `_configure_logging()` called at the start. Worker exceptions are caught and logged as errors (though `_download_single_ticker` already catches all exceptions and returns `None`).

### ✅ M8 — `OPENAI_API_KEY` absence fails silently until first LLM call
**File:** `chains.py:1`, `financialtools/analysis.py`
**Owner:** API & DX
**Resolution:** Two-site change: (1) `chains.py` — module-level guard added after `load_dotenv()` (safe here since `chains.py` is not imported in any unit test); (2) `analysis.py` — guard added inside `run_topic_analysis()` before any network or LLM work (not at module level, to avoid breaking unit tests that import the module without an API key set). Both raise `EnvironmentError` with a clear message pointing to the `.env` file. `import os` added to `analysis.py` imports.

### ✅ M9 — `RateLimiter` belongs in `utils.py`, not `processor.py`
**File:** `financialtools/processor.py:15`
**Owner:** Architecture & Code Quality
**Resolution:** `RateLimiter` class (65 lines) moved to `financialtools/utils.py`. Deferred `import threading` replaced with a top-level `import threading`. `from time import sleep` replaced with `time.sleep(...)` for consistency. In `processor.py`, the class body replaced with `from financialtools.utils import RateLimiter  # noqa: F401` so that `from financialtools.processor import RateLimiter` continues to work without change. Unused `from time import sleep` removed from `processor.py`. `RateLimiter` added to `financialtools/__init__.py`.

### ✅ M10 — `cache_key` separator could theoretically collide
**File:** `agents/_cache.py:51`
**Owner:** Performance & Reliability
**Resolution:** Separator changed from `_` to `__` (double underscore). `::` was the originally suggested separator but is invalid on Windows (`:`is a reserved character in Windows paths). `__` is safe on all platforms and eliminates the collision: `cache_key("TICKER_A", 2023)` → `"TICKER_A__2023"` is unambiguous even for tickers containing underscores (e.g. `BRK_B`). Docstring examples updated. Cache layout comment in module docstring updated. Existing `.cache/` entries use the old naming and will be treated as cache misses, triggering a fresh download — the safe behavior.

---

## Prioritized Action Items

| Priority | Issue | Status | Owner | File |
|---|---|---|---|---|
| P0 | C1 — RateLimiter holds lock during sleep | ✅ Fixed | Performance | `processor.py:48` |
| P0 | C2 — FundamentalEvaluator passes dict as weights | ✅ Fixed | API & DX | `wrappers.py:177` |
| P1 | S1 — _invoke_chain retry logic bug (3 calls) | ✅ Fixed | Devil's Advocate | `analysis.py:326` |
| P1 | S2 — evaluate() swallows failures silently | ✅ Fixed | Devil's Advocate | `processor.py:evaluate()` |
| P1 | S3 — merge_results crashes on None results | ✅ Fixed | Performance | `wrappers.py:233` |
| P1 | S4 — from_ticker() swallows all exceptions | ✅ Fixed | Performance | `processor.py:from_ticker` |
| P1 | S5 — private helpers imported cross-package | ✅ Fixed | Architecture | `analysis.py:build_weights` |
| P1 | S6 — no cache invalidation | ✅ Fixed | Performance | `_cache.py:clear_cache` |
| P2 | M1 — dead weight dicts in config.py | ✅ Fixed | Architecture | `config.py:30` |
| P2 | M2 — chains.py has no deprecation marker | ✅ Fixed | Devil's Advocate | `chains.py` |
| P2 | M3 — __init__.py exports nothing | ✅ Fixed | API & DX | `__init__.py` |
| P3 | M4 — architecture.md wrong module locations | ✅ Fixed | Architecture | `architecture.md` |
| P3 | M5 — wrappers.py module-level logging | ✅ Fixed | Architecture | `wrappers.py` |
| P3 | M6 — SCORED_METRICS not enforced by test | ✅ Fixed | Architecture | `test_processor.py` |
| P3 | M7 — _download_multiple_tickers sequential | ✅ Fixed | API & DX | `wrappers.py` |
| P3 | M8 — OPENAI_API_KEY silent failure | ✅ Fixed | API & DX | `chains.py`, `analysis.py` |
| P3 | M9 — RateLimiter in wrong module | ✅ Fixed | Architecture | `utils.py` |
| P3 | M10 — cache_key separator collision risk | ✅ Fixed | Performance | `_cache.py` |

---

---

## Quality Audit Fixes (2026-04-18)

Bugs identified by automated reliability audit; all fixed in `main`.

| Issue | Status | File |
|---|---|---|
| QA-P0-1 — `test_financial_agent.py` asserts single-underscore cache keys (wrong contract) | ✅ Fixed | `tests/test_financial_agent.py:45,49,53,170` |
| QA-P0-2 — `enrich_tickers()` crashes with `ValueError` when all profiles fail | ✅ Fixed | `financialtools/utils.py:enrich_tickers` |
| QA-P1-1 — `resolve_sector()` returns newline-joined string for multi-row info_df, silently selecting wrong sector weights | ✅ Fixed | `financialtools/utils.py:resolve_sector` |
| QA-P1-2 — `_download_single_ticker` sets `company_name` to newline-joined string for multi-row info_df | ✅ Fixed | `financialtools/wrappers.py:_download_single_ticker` |
| QA-P1-3 — `dataframe_to_json` raises `ValueError` on NaN/Inf values; LLM payloads fail for banks/foreign tickers | ✅ Fixed | `financialtools/utils.py:dataframe_to_json` |
| QA-P1-4 — `safe_div` crashes with `AttributeError` when `num`/`den` is a scalar (no `.notna()`) | ✅ Fixed | `financialtools/evaluator.py:safe_div` |

### QA-P0-1 — Cache key test assertions used single-underscore format
`cache_key()` was changed to double-underscore separator (M10, 2026-04-16) but four test assertions in `TestCacheUtils` and `TestPrepareFinancialDataTool` retained the old single-underscore values. Tests were asserting a contract that no longer existed. Updated to `"AAPL__2023"`, `"ENI.MI__all"`, `"MSFT__2022"`.

### QA-P0-2 — `enrich_tickers()` crashes on total failure
`pd.concat([])` raises `ValueError: No objects to concatenate`. Added early-return guard: if `profiles` is empty after the loop, return an empty `pd.DataFrame()` with a WARNING log. Callers can distinguish empty result from exception.

### QA-P1-1 — `resolve_sector()` multi-row bug
`info_df["sector"].str.lower().to_string(index=False)` on a multi-row Series produced `"technology\nfinancial-services"` which never matched any sector key, silently falling back to `"default"` weights. Fixed: `.iloc[0].lower()` — take the first row only.

### QA-P1-2 — `_download_single_ticker` `company_name` multi-row bug
Same `.to_string(index=False)` pattern applied to `info_df["longName"]` produced a newline-joined string when `get_info_data()` returned multiple rows. Fixed: `.iloc[0].lower().strip()`.

### QA-P1-3 — `dataframe_to_json` rejects NaN/Inf
Standard JSON does not allow `NaN` or `Infinity`. `json.dumps` raises `ValueError` for these values, which are common in metrics DataFrames for banks and foreign tickers. Fixed: replace `±Inf` with `None`, then replace `NaN` with `None` via `.where(df.notna(), other=None)` before serialising.

### QA-P1-4 — `safe_div` scalar input crash
When `num` or `den` is a plain Python scalar (e.g. a constant), `den.notna()` raises `AttributeError`. The bare `except Exception` then attempted `len(num)` which also fails for scalars, returning an empty array and silently corrupting metric columns. Fixed: cast both operands to `pd.Series` at entry. Return type annotation added: `-> np.ndarray`.

---

## What Is Done Well

- **Invariant documentation is thorough.** `processor.py`, `_cache.py`, `graph_nodes.py` all carry clear invariant blocks that explain contract, failure mode, and data flow.
- **`config.py` is pure Python** — no I/O at import, no side effects. Single source of truth for scoring weights, with DRY extension blocks (`_STD_EXT`, `_FIN_EXT`, `_RE_EXT`).
- **`_empty_result()` shape contract** is correctly enforced — all callers use the factory function, never a shallow copy.
- **`FundamentalTraderAssistant` validation is fast-fail.** Empty or multi-ticker DataFrames raise `EvaluationError` immediately in `__init__` with a clear message.
- **`score_metric()` and `metrics_red_flags()` return copies** — no silent mutation of the input DataFrame.
- **`prompts.py` build factory** correctly applies the DRY principle — adding a new metric requires editing one block constant, not every prompt string.
- **The agent architecture is clean** — `prepare_data_node` is the only download site, topic subgraphs are stateless, and state flows through `AnalysisState` rather than disk.
- **Logging is structured** — `[ticker]` prefix on all log lines makes filtering trivial.
