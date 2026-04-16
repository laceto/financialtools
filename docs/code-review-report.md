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
| M1–M10 | ⬜ Open | various |

---

## Executive Summary

1. ~~One **critical correctness bug**: `RateLimiter` holds its lock during `sleep()`, serialising all threads.~~ **Fixed.**
2. ~~One **blocking API bug**: `FundamentalEvaluator` passes a raw `dict` where `FundamentalTraderAssistant` expects a `pd.DataFrame`.~~ **Fixed.**
3. ~~The **retry logic in `_invoke_chain`** makes 3 LLM calls on a parse error instead of 2, and fixes the wrong output.~~ **Fixed.**
4. ~~**Silent `_empty_result()` on `evaluate()` failure** propagates empty DataFrames to the LLM unchecked, producing hallucinated assessments.~~ **Fixed.**
5. The **public API surface is empty** — `__init__.py` exports nothing; two dead config dicts inflate `config.py` by ~170 lines.

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

### M1 — `sector_metric_weights` and `grouped_weights` in `config.py` appear unused
**File:** `financialtools/config.py:30–202`
**Owner:** Architecture & Code Quality

Neither structure is imported by any live code path. Both add ~170 lines. Remove after confirming no notebook usage, or add a comment with their intended use case.

### M2 — `chains.py` is likely legacy with no deprecation marker
**File:** `chains.py`
**Owner:** Devil's Advocate / Architecture

`chains.py` reads pre-computed Excel files. `analysis.py` is self-contained. No doc or comment tells callers which to prefer.

**Fix:** Add `# DEPRECATED: prefer financialtools.analysis.run_topic_analysis()` at the top of `chains.py`, or remove it if no callers remain.

### M3 — `__init__.py` exports nothing
**File:** `financialtools/__init__.py`
**Owner:** API & DX

Empty init means no public API contract. Add explicit re-exports for the primary surface: `Downloader`, `DownloaderWrapper`, `FundamentalTraderAssistant`, `FundamentalEvaluator`, `run_topic_analysis`, and all exception classes.

### M4 — `architecture.md` incorrectly lists package files as "repo root"
**File:** `architecture.md` module table
**Owner:** Architecture & Code Quality

`analysis.py`, `pydantic_models.py`, `prompts.py` are inside `financialtools/`, not at repo root. Only `chains.py` is at repo root. The doc misleads contributors.

### M5 — `wrappers.py` configures file handlers at module import time
**File:** `financialtools/wrappers.py:22–46`
**Owner:** Architecture & Code Quality

Three `FileHandler` instances are opened and `logs/` is created on every import. Tests that import `DownloaderWrapper` create log files as a side effect. Move handler setup to a lazy init or explicit `configure_logging()`.

### M6 — `SCORED_METRICS` list is documentation, not enforcement
**File:** `financialtools/processor.py:338–365`
**Owner:** Architecture & Code Quality

`evaluate()` derives scored columns dynamically, so `SCORED_METRICS` can silently drift from reality. Add a test: `assert set(SCORED_METRICS) == set(actual_scored_columns_from_compute_metrics)`.

### M7 — `_download_multiple_tickers` is sequential, not parallel
**File:** `financialtools/wrappers.py:127–140`
**Owner:** API & DX

Name and placement imply parallel download, but it is a for-loop. Document the sequential behavior or parallelize with `ThreadPoolExecutor`.

### M8 — `OPENAI_API_KEY` absence fails silently until first LLM call
**File:** `chains.py:1`, `financialtools/analysis.py:57`
**Owner:** API & DX

Add an early guard at module load:
```python
import os
if not os.getenv("OPENAI_API_KEY"):
    raise EnvironmentError("OPENAI_API_KEY not set — check your .env file")
```

### M9 — `RateLimiter` belongs in `utils.py`, not `processor.py`
**File:** `financialtools/processor.py:15`
**Owner:** Architecture & Code Quality

`RateLimiter` is a generic threading utility with no financial domain logic. Move to `utils.py`.

### M10 — `cache_key` separator could theoretically collide
**File:** `agents/_cache.py:51`
**Owner:** Performance & Reliability

`cache_key("TICKER_A", 2023)` → `"TICKER_A_2023"`. Low probability today, but use `"::"` as separator for safety.

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
| P2 | M1 — dead weight dicts in config.py | ⬜ Open | Architecture | `config.py:30` |
| P2 | M2 — chains.py has no deprecation marker | ⬜ Open | Devil's Advocate | `chains.py` |
| P2 | M3 — __init__.py exports nothing | ⬜ Open | API & DX | `__init__.py` |
| P3 | M4–M10 — docs, logging, naming improvements | ⬜ Open | Architecture / DX | various |

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
