# Issue Tracker — financialtools

Source: devils-advocate audit, 2026-04-20.

---

## Legend

| Status | Meaning |
|--------|---------|
| `open` | Not yet addressed |
| `in-progress` | Work started |
| `resolved` | Fixed and merged |
| `wont-fix` | Accepted risk, documented |

---

## Summary Table

| ID | Severity | Status | PR / Commit |
|----|----------|--------|-------------|
| [P0-1](#p0-1) | P0 | `resolved` | — |
| [P0-2](#p0-2) | P0 | `open` | — |
| [P0-3](#p0-3) | P0 | `open` | — |
| [P1-1](#p1-1) | P1 | `resolved` | — |
| [P1-2](#p1-2) | P1 | `resolved` | — |
| [P1-3](#p1-3) | P1 | `open` | — |
| [P1-4](#p1-4) | P1 | `open` | — |
| [P1-5](#p1-5) | P1 | `open` | — |
| [P1-6](#p1-6) | P1 | `resolved` | — |
| [P1-7](#p1-7) | P1 | `open` | — |
| [P2-1](#p2-1) | P2 | `resolved` | — |
| [P2-2](#p2-2) | P2 | `open` | — |
| [P2-3](#p2-3) | P2 | `open` | — |
| [P2-4](#p2-4) | P2 | `resolved` | — |
| [P2-5](#p2-5) | P2 | `resolved` | — |
| [P2-6](#p2-6) | P2 | `resolved` | — |

---

## P0 — Breaking

### P0-1

**Status:** `resolved` | **Location:** `evaluator.py:293–296`

**Finding:** Silent all-NaN analysis on yfinance column mismatch — 15+ hardcoded column accesses in `compute_metrics`, only 5 guarded by `_REQUIRED_METRIC_COLS`. A yfinance column rename produces `EvaluationError` with no actionable detail (the real `KeyError` is swallowed by a catch-all `except Exception`).

**Suggested fix:**
- Replace all hard bracket column accesses in `compute_metrics` with `d.get(col, pd.Series(np.nan, index=d.index))` — the same pattern already used for optional columns on lines 232–274.
- Extend `_REQUIRED_METRIC_COLS` to cover all non-optional columns.
- Add a startup diff check that logs a clear message listing expected vs. received columns when any required column is missing.

---

### P0-2

**Status:** `open` | **Location:** `analysis.py:457–461`

**Finding:** 9 sequential LLM calls per `run_topic_analysis` call, no timeout, no cost cap, no progress signal. Blocks the calling thread for 45–135 seconds. Estimated ~$0.30–$1.50 per ticker. The fix-retry path in `invoke_chain` can double this to 18 calls with no budget guard.

**Suggested fix:**
- Run the 9 topic chains concurrently with `asyncio.gather` or `ThreadPoolExecutor(max_workers=9)`.
- Add a `timeout_per_call` parameter passed to `ChatOpenAI(request_timeout=30)`.
- Log progress after each topic completes (topic name + elapsed time).
- Document the approximate cost per call in the `run_topic_analysis` docstring.

---

### P0-3

**Status:** `open` | **Location:** `downloader.py:67–90`

**Finding:** The yfinance info call has no timeout. A rate-limited or malformed partial JSON response from yfinance causes `pivot` to raise `ValueError`, which the outer `except Exception` collapses into a single `DownloadError` — losing all four already-fetched data sources and providing no indication of which call failed.

**Suggested fix:**
- Fetch the four data sources (info, balance sheet, income statement, cash flow) with individual `try/except` blocks so a failure in one does not discard the others.
- Treat a failed info fetch as a warning (not fatal) — `_info` is only used for market cap and price, which already have NaN fallbacks.
- Wrap the info call with a timeout using `concurrent.futures.wait(..., timeout=10)` (compatible with Windows).

---

## P1 — Serious (Wrong Results or Slow at Scale)

### P1-1

**Status:** `resolved` | **Location:** `evaluator.py:310, 334`

**Finding:** Negative-equity companies score 5/5 on `DebtToEquity`. `safe_div` returns a negative ratio when book equity is negative (common for buyback-heavy or distressed companies). `np.digitize` maps negative values to bucket 0, and the inversion `6 - 1 = 5` assigns the best possible score — financially backwards.

**Suggested fix:**
- In `_score_metric`, add a guard: if the metric is `DebtToEquity` and the value is negative, return score 1 (maximum risk) instead of running through the threshold buckets.
- Document in `_SCORE_THRESHOLDS` comments which metrics produce undefined or misleading values for negative-equity companies.

---

### P1-2

**Status:** `resolved` | **Location:** `pydantic_models.py:39`

**Finding:** `regime: Literal["bull", "bear"]` forces a binary classification on a domain where "neutral" is the modal true state. The LLM is forced to choose an extreme for every stock, regardless of whether fundamentals actually support it.

**Suggested fix:**
- Add `"neutral"` to the `regime` Literal: `Literal["bull", "bear", "neutral"]`.
- Update the field description to define what each value means in terms of observable fundamentals (e.g., "bull = improving revenue + margin expansion + positive FCF trend").

---

### P1-3

**Status:** `open` | **Location:** `pydantic_models.py:73`, `analysis.py:29–30`

**Finding:** `market_comparison: str = Field(...)` is a required non-Optional field, but no market comparison data is ever sent to the LLM (the design invariant comment at `analysis.py:29` confirms this). The LLM fabricates a market comparison on every single call.

**Suggested fix:**
- Change to `market_comparison: Optional[str] = Field(None, description="None when no benchmark data is available.")`.
- Handle `None` in downstream serialization and display.
- If benchmark data integration is planned, document it as a future requirement here.

---

### P1-4

**Status:** `open` | **Location:** `agents/_cache.py:94–123`

**Finding:** The disk cache has no TTL, no file locking, and no integrity check. Two concurrent threads analyzing the same ticker can interleave reads and writes, producing corrupted JSON. Stale financial data (months or years old) is served as current with no staleness indicator.

**Suggested fix:**
- Add `"written_at": time.time()` to every payload written by `write_payloads`.
- Add a `max_age_hours` parameter to `read_payloads` that raises `FileNotFoundError` (triggering re-download) when the cache is stale.
- Use an atomic write pattern: write to a temp file then `os.replace(tmp, final)` — this is atomic on both POSIX and Windows and eliminates the concurrent-write corruption risk.

---

### P1-5

**Status:** `open` | **Location:** `utils.py:231–254`

**Finding:** `enrich_tickers` loops over every ticker with only `time.sleep(0.5)` between calls — no `RateLimiter`, no concurrency, no retry. For 100 tickers, this trips yfinance rate limits around call 25 and silently returns a shorter DataFrame than expected (the `except Exception` at line 246 logs and continues).

**Suggested fix:**
- Accept an optional `RateLimiter` parameter; default to `RateLimiter(per_minute=20)`.
- Use `ThreadPoolExecutor(max_workers=4)` with the limiter to parallelize calls.
- Log progress every 10 tickers so the caller has visibility into partial completion.
- Return a count of failed enrichments alongside the result DataFrame.

---

### P1-6

**Status:** `resolved` | **Location:** `wrappers.py:89`

**Finding:** `time.sleep(2)` inside `_download_single_ticker` imposes a 2-second delay on every download regardless of actual rate-limit pressure. In a 4-worker pool over 20 tickers, this adds at least 10 seconds of pure sleep on top of actual network time. `RateLimiter` already exists for this purpose.

**Suggested fix:**
- Remove the hardcoded `time.sleep(2)`.
- Add an optional `limiter: RateLimiter | None = None` parameter to `_download_multiple_tickers`.
- Default to `RateLimiter(per_minute=20)` inside that function so the delay is adaptive, not fixed.

---

### P1-7

**Status:** `open` | **Location:** `utils.py:168`

**Finding:** `resolve_sector` returns the raw lowercased/dashed yfinance `sectorKey` without validating it against `sec_sector_metric_weights`. A yfinance taxonomy change produces an unrecognized key that silently falls through to default weights in `build_weights` — the caller receives the wrong sector string with no indication that fallback occurred.

**Suggested fix:**
- After computing the candidate key, check `if key not in sec_sector_metric_weights`.
- If not found, log a WARNING with the unrecognized value and explicitly return `"default"` (not the unrecognized string).
- This makes the fallback visible at the call site rather than buried in `build_weights`.

---

## P2 — Structural Debt

### P2-1

**Status:** `resolved` | **Location:** `processor.py:16–18`, `__init__.py:33`

**Finding:** Private internals (`_empty_result`, `_EMPTY_RESULT_KEYS`, `_REQUIRED_METRIC_COLS`) are re-exported as public API via `processor.py` and `__init__.py`. They have propagated into `wrappers.py` as a dependency, making the internal result shape a public contract that cannot be changed without breaking callers.

**Suggested fix:**
- Create a proper public factory function `empty_result()` (no underscore) in `evaluator.py` that wraps `_empty_result()`.
- Export only `empty_result` from `__init__.py`.
- Remove `_empty_result`, `_EMPTY_RESULT_KEYS`, and `_REQUIRED_METRIC_COLS` from the public surface.

---

### P2-2

**Status:** `open` | **Location:** `tests/`, `analysis.py:291–333`

**Finding:** All tests mock out the LLM layer entirely. The fix-retry path in `invoke_chain` (the most complex error-handling code in the library) has no test. A prompt-format change or Pydantic model field rename would silently break parsing with no test failure.

**Suggested fix:**
- Add one integration test (gated with `@unittest.skipUnless(os.getenv("OPENAI_API_KEY"), "requires API key")`) that runs `invoke_chain` with a real LLM call against a known small payload.
- Add a unit test for the fix-retry path by mocking `parser.invoke` to raise on the first call and succeed on the second.
- Add a test asserting all five payload JSON strings are deserializable by `json.loads`.

---

### P2-3

**Status:** `open` | **Location:** `requirements.txt`

**Finding:** `requirements.txt` is a full pip-freeze including Windows-only (`pywin32`), database (`mysqlclient`, `peewee`), dev (`debugpy`, `ipykernel`), and visualization (`polars`, `altair`) packages. Installation fails on Linux due to `mysqlclient` and `pywin32`. File may have a UTF-16-LE encoding issue.

**Suggested fix:**
- Create a `pyproject.toml` with `[project.dependencies]` listing only runtime requirements: `yfinance`, `pandas`, `numpy`, `langchain-openai`, `langchain-core`, `langgraph`, `pydantic`, `python-dotenv`.
- Move dev, notebook, and visualization deps to `[project.optional-dependencies]` groups.
- Re-save `requirements.txt` as UTF-8 if the encoding issue is confirmed.

---

### P2-4

**Status:** `resolved` | **Location:** `wrappers.py:41`

**Finding:** `os.makedirs(_LOGS_DIR, exist_ok=True)` inside `_configure_logging` has no `try/except`. On a read-only filesystem (e.g., a Docker image with an immutable `/app`), the first download call raises an unhandled `PermissionError` that looks unrelated to the actual operation.

**Suggested fix:**
- Wrap the `makedirs` call in `try/except PermissionError` and fall back to `logging.StreamHandler` (stderr) with a one-time warning: `"Cannot create log directory {_LOGS_DIR}, falling back to stderr logging."`.
- Alternatively, make the log directory configurable via `FINANCIALTOOLS_LOG_DIR` environment variable.

---

### P2-5

**Status:** `resolved` | **Location:** `config.py:81–309`

**Finding:** Two parallel sector weight dictionaries exist (`sector_metric_weights` legacy title-case and `sec_sector_metric_weights` current). The legacy dict is undocumented as deprecated and has no guard preventing accidental import in new code. When the two dicts diverge, analysis results differ between callers silently.

**Suggested fix:**
- Delete `sector_metric_weights` entirely, keeping only a comment explaining its former existence.
- If backward compatibility is required, wrap it in a `DeprecationWarning` via a module-level `__getattr__` guard.
- Add a CI-checked test asserting that `sec_sector_metric_weights` has entries for every sector in the yfinance taxonomy.

---

### P2-6

**Status:** `resolved` | **Location:** `evaluator.py:358`

**Finding:** `_score_metric` uses `df.apply(score_row, axis=1)` — Python-level row iteration. The `score_row` closure captures `self`, making the function non-picklable (blocks any future move to `ProcessPoolExecutor`). At batch scale (50+ tickers), the per-row overhead is measurable.

**Suggested fix:**
- Vectorize using `np.digitize` directly on the metric series, grouped by metric name.
- Use a `pd.Series.map` + `np.digitize` approach that eliminates the row-by-row loop entirely.
- This also removes the closure over `self`, making `_score_metric` independently testable and picklable.

---

## Resolved

| ID | Finding | Resolved in | Notes |
|----|---------|-------------|-------|
| P0-1 | Silent all-NaN analysis on yfinance column mismatch | `evaluator.py` — `_fill_missing_cols` helper + expanded `_REQUIRED_METRIC_COLS` + 5 new tests | `_REQUIRED_METRIC_COLS` now covers all 12 core columns; single consolidated WARNING emitted |
| P1-1 | Negative-equity companies score 5/5 on DebtToEquity | `evaluator.py` — guard in `score_row` before inversion + 5 new tests in `TestNegativeEquityScoring` | Negative D/E → score 1 (maximum risk); positive D/E inversion unchanged |
| P1-2 | Binary bull/bear regime forces LLM into extremes | `pydantic_models.py` — added `"neutral"` to both `regime` Literals + descriptions; `app.py` color map; new `tests/test_pydantic_models.py` | 9 tests covering all three values and invalid rejection |
| P1-6 | Hardcoded 2-second sleep per download worker | `wrappers.py` — removed `time.sleep(2)`; added `limiter` param to both functions; `_download_multiple_tickers` defaults to `RateLimiter(per_minute=20)`; new `tests/test_wrappers.py` | 6 tests covering acquire call count, default creation, and sleep regression |
| P2-1 | Private internals exported as public API | `evaluator.py` — added `empty_result()` public factory; `processor.py` — removed private names from re-exports and `__all__`; `wrappers.py` + `scripts/run_pipeline.py` migrated; `__init__.py` — exports `empty_result` + backward-compat alias | Verified via `processor.__all__` assertion |
| P2-6 | Row-by-row `apply` in `_score_metric` | `evaluator.py` — replaced `df.apply(score_row)` with vectorized loop over `_SCORE_THRESHOLDS` using `np.digitize` per metric group; P1-1 guard applied as final boolean mask; `TestScoreMetricVectorized` (4 tests) | 90 tests pass; scores identical to old implementation |
| P2-4 | `makedirs` unguarded in `_configure_logging` | `wrappers.py` — `makedirs` + `FileHandler` setup wrapped in `try/except OSError`; fallback adds `StreamHandler` + WARNING naming `FINANCIALTOOLS_LOG_DIR`; `_LOGS_DIR` reads env var first; 6 new tests in `TestConfigureLogging` | 96 tests pass |
| P2-5 | Two parallel sector weight dicts in config.py | `config.py` — deleted `sector_metric_weights` (142 lines), replaced with tombstone comment; `tests/test_config.py` — regression guard + 4 structural tests on `sec_sector_metric_weights` | 101 tests pass |

---

## Open Questions

- [ ] **P0-2** — What is the accepted cost budget per `run_topic_analysis` call? Is there a per-session cap?
- [ ] **P1-3** — Is `market_comparison` intentionally unfilled, awaiting benchmark data integration?
- [ ] **P1-4** — What is the expected cache TTL? Should it match yfinance's quarterly reporting cadence?
- [ ] **P1-1** — Are `_SCORE_THRESHOLDS` empirically calibrated or set by domain intuition? Document as heuristics if the latter.
- [ ] **P2-3** — Why does `requirements.txt` include `mysqlclient` and `peewee`? Is there an undocumented database layer?
