# Code Review: processor_guide.ipynb

**Review Date:** 2026-03-20
**Reviewer:** Claude Code
**File:** `notebooks/processor_guide.ipynb`

---

## Executive Summary

The notebook is well-structured, with clear section headers, good inline commentary, and
accurate prose documentation following the recent metric expansion. However, a single
**critical runtime bug** (`NameError` on `data`) will crash Section 5 for any reader who
runs the notebook top-to-bottom. Beyond that, **stale output cells** actively contradict
the updated markdown (showing 11 metrics / 5 keys while the prose says 24 / 6), and
Sections 6–9 listed in the table of contents are completely absent. The notebook is not
currently safe to ship as documentation.

---

## Findings

### 🔴 Critical Issues (Count: 1)

#### Issue 1: `NameError` — `data` is undefined in cell `c56mfhuudep`
**Severity:** Critical
**Category:** Correctness
**Cell:** `c56mfhuudep`

**Description:**
The red-flag injection block uses `data.copy()`, but `data` was renamed to `merged` in the
previous update to the notebook. The variable `data` is never assigned in any prior cell.
Running the notebook top-to-bottom will raise `NameError: name 'data' is not defined` at
the `data_bad = data.copy()` line, aborting section 5 mid-cell.

**Current Code:**
```python
# Force a red-flag scenario by injecting bad values into the first two rows.
data_bad = data.copy()
data_bad.loc[data_bad.index[0], "free_cash_flow"] = -500_000_000
data_bad.loc[data_bad.index[1], "net_income_common_stockholders"] = -200_000_000
```

**Impact:**
- Notebook execution fails for every reader who runs all cells in order.
- The red-flag injection scenario — the most educational part of section 5 — is
  completely unreachable.
- Stale output from a prior run is displayed, masking the bug from casual readers.

**Recommendation:**
Rename the variable to `merged` to match the live variable in scope.

**Proposed Fix:**
```python
# Force a red-flag scenario by injecting bad values into the first two rows.
data_bad = merged.copy()
data_bad.loc[data_bad.index[0], "free_cash_flow"] = -500_000_000
data_bad.loc[data_bad.index[1], "net_income_common_stockholders"] = -200_000_000
```

---

### 🟠 High Priority Issues (Count: 2)

#### Issue 2: Stale output in cell `bwx1ym2jbc7` contradicts current markdown
**Severity:** High
**Category:** Correctness / Cognitive Debt
**Cell:** `bwx1ym2jbc7`

**Description:**
The output of this cell was captured before the metric expansion and shows:
- `SCORED_METRICS (11 items)` — actual count is **24**
- `_EMPTY_RESULT_KEYS : ('metrics', 'eval_metrics', 'composite_scores', 'raw_red_flags', 'red_flags')` — **5 keys**, actual count is **6** (missing `'extended_metrics'`)
- `_empty_result() keys` / `Distinct objects` similarly show 5, not 6

The markdown cell immediately above (`lompqa4lt5`) correctly states "**24** metric column
names" and "**6** keys". A reader sees the prose say one thing and the output say another,
with no indication which to trust.

**Impact:**
- Destroys reader confidence in the notebook as documentation.
- A developer using these outputs to build a downstream tool would construct a 5-key
  result schema and miss `extended_metrics`.

**Recommendation:**
Clear the stale output and re-execute the cell after fixing Issue 1, then save with outputs.
Until then, add a `# ⚠️ STALE OUTPUT — run this notebook to refresh` comment in the cell
body as a temporary signal.

---

#### Issue 3: Sections 6–9 absent — TOC links to non-existent content
**Severity:** High
**Category:** Maintainability / Completeness
**Cell:** `md-placeholder` (header cell)

**Description:**
The notebook's table of contents lists four sections that have no corresponding cells:

```
6. [Downloader (Live)](#6-downloader-live)
7. [Error handling](#7-error-handling)
8. [Common failure modes](#8-common-failure-modes)
9. [End-to-end pattern](#9-end-to-end-pattern)
```

The `stream_download()` classmethod, `combine_merged_data()`, and the end-to-end
`evaluate → export` pattern described in `CLAUDE.md` are entirely undocumented.
The error-handling and common-failure-modes sections referenced in the prerequisites block
("Sections 1–3 and 7–9 run with no API key") also do not exist.

**Impact:**
- Error-handling patterns (what to do when `from_ticker()` returns an empty Downloader,
  how to interpret `_empty_result()` in production) are undocumented.
- The "no internet needed for sections 7–9" prerequisite note is misleading — those
  sections are placeholders.

**Recommendation:**
Either implement the four missing sections or remove them from the TOC and prerequisites
note until they are ready. Implementing section 7 (Error handling) is highest value as it
covers the most common failure modes new users encounter.

---

### 🟡 Medium Priority Issues (Count: 3)

#### Issue 4: Three cells have no outputs (never re-executed after last edit)
**Severity:** Medium
**Category:** Maintainability / Observability
**Cells:** `pc13aqukl1m`, `6n559gn69hu`, `tkft62xl74`

**Description:**
Cells `pc13aqukl1m` (market column verification), `6n559gn69hu` (weights construction +
FTA construction), and `tkft62xl74` (`evaluate()` result display) were edited in the last
notebook update but never re-run. They have empty output. A reader cannot verify that the
notebook executes correctly for sections 4–5.

**Recommendation:**
Run the notebook end-to-end against a live internet connection and save with outputs.

---

#### Issue 5: `info` variable fetched but unused after auto-enrichment change
**Severity:** Medium
**Category:** Cognitive Debt
**Cell:** `ew6ume5ukvw`

**Description:**
```python
info = d.get_info_data()
print(f"info   shape : {info.shape}")
```
`info` is assigned and printed, but is never referenced in any subsequent cell. Before the
auto-enrichment change (`get_merged_data()` now broadcasts market columns), section 4
previously used `info` to manually merge market data. That merge code has been removed,
but the `get_info_data()` call was left in. This creates a false expectation that `info`
is a required input to `FundamentalTraderAssistant`.

**Impact:**
- Readers unfamiliar with the recent change may think they need to pass `info` somewhere.
- Adds noise to the cell without explanatory value.

**Recommendation:**
Remove the `info = d.get_info_data()` line and its `print`. If demonstrating `get_info_data()`
is still desirable (it is a public API method), move it to a dedicated cell in section 6
(Downloader Live) with a clear note that it is *optional* when using `get_merged_data()`.

---

#### Issue 6: `sec_sector_metric_weights` vs `sector_metric_weights` key convention undocumented
**Severity:** Medium
**Category:** Cognitive Debt
**Cell:** `6n559gn69hu`

**Description:**
`SECTOR = "technology"` uses the yfinance `sectorKey` lowercase convention required by
`sec_sector_metric_weights`. A reader who previously used `sector_metric_weights` (which
uses title-case keys like `"Technology Services"`) will get a `KeyError` if they swap
the dict. The inline comment `# key in sec_sector_metric_weights (lowercase)` is present
but easy to miss.

**Impact:**
- `KeyError: 'Technology'` is the most likely first error new users encounter when
  adapting the notebook to their own ticker.

**Recommendation:**
Add a short note to the markdown in section 4 explaining the two weight dicts and their
key conventions:

```markdown
> **Weight dict key convention:**
> - `sec_sector_metric_weights` uses yfinance `sectorKey` lowercase strings (e.g. `"technology"`, `"financial-services"`).
> - `sector_metric_weights` uses display-name strings (e.g. `"Technology Services"`, `"Financials"`).
> Use `sec_sector_metric_weights` when building from a `Downloader` result; use
> `sector_metric_weights` when the sector is known from an external source.
```

---

### 🟢 Low Priority Issues (Count: 2)

#### Issue 7: Thread-safety demo never shows blocking behaviour
**Severity:** Low
**Category:** Explainability
**Cell:** `qhz8cgbfd3`

**Description:**
The demo uses `per_minute=5` and fires exactly 5 threads — so 0 threads ever block. The
comment says "a 6th would block" but doesn't show it. A reader cannot see what happens at
the limit — the most important characteristic of a rate limiter.

**Recommendation:**
Add a second mini-demo with `per_minute=2` and 3 threads (or a 4-thread variant) and time
the output to show that the third call is delayed. This is a low-effort addition with high
explanatory value.

---

#### Issue 8: Red-flag injection comment says "first two rows" but modifies `index[0]` and `index[1]`
**Severity:** Low
**Category:** Explainability
**Cell:** `c56mfhuudep`

**Description:**
The comment `# Force a red-flag scenario by injecting bad values into the first two rows`
is accurate, but the code uses `.index[0]` and `.index[1]` without checking whether those
rows correspond to the earliest dates. If the DataFrame's `time` column is not sorted
ascending (it isn't guaranteed), the injection may target the two *arbitrary* first rows
rather than the two *earliest* year rows.

**Recommendation:**
Sort by `time` before injecting to make the intent explicit and the output deterministic:
```python
data_bad = merged.copy().sort_values("time").reset_index(drop=True)
data_bad.loc[0, "free_cash_flow"] = -500_000_000
data_bad.loc[1, "net_income_common_stockholders"] = -200_000_000
```

---

## Positive Observations

- Markdown cells are detailed and accurate post-update: the scored/unscored split, inverse
  scoring note, and `evaluate()` return key table are all correct.
- The `_empty_result()` factory warning (shallow copy hazard) is a proactive, non-obvious
  invariant that is genuinely helpful.
- The `from_ticker()` never-raises contract is clearly communicated with the guard check
  (`if merged.empty: raise RuntimeError(...)`).
- `_MARKET_COLS` is accessed via the class attribute (`Downloader._MARKET_COLS`) rather
  than hardcoded strings — correct single-source-of-truth usage.
- Prerequisites block (internet-required sections) is a good UX choice for a technical
  notebook.

---

## Action Plan

### Phase 1: Critical Fix (Before Merging / Sharing)
- [x] ~~Bug:~~ Fix `data.copy()` → `merged.copy()` in cell `c56mfhuudep`
- [ ] Re-execute notebook end-to-end and save with fresh outputs

### Phase 2: High Priority (This Sprint)
- [ ] Clear stale output in cell `bwx1ym2jbc7` (or add `⚠️ STALE OUTPUT` comment)
- [ ] Implement section 7 (Error handling) — `EvaluationError` guards, `_empty_result`
      contract, and `DownloadError` pattern
- [ ] Either add sections 8–9 or remove them from the TOC and prerequisites note

### Phase 3: Medium Priority (Next Sprint)
- [ ] Remove dead `info = d.get_info_data()` from cell `ew6ume5ukvw`
- [ ] Add `sec_sector_metric_weights` vs `sector_metric_weights` key-convention note to
      section 4 markdown

### Phase 4: Low Priority (Backlog)
- [ ] Extend thread-safety demo to show blocking behaviour
- [ ] Sort `data_bad` by `time` before injecting red-flag values

---

## Technical Debt Estimate

- **Total Issues:** 8 (1 critical, 2 high, 3 medium, 2 low)
- **Estimated Fix Time:** 3–5 hours (including implementing sections 7–9)
- **Risk Level:** High (critical runtime bug + stale outputs actively mislead readers)
- **Recommended Refactor:** No — targeted fixes only; structure is sound
