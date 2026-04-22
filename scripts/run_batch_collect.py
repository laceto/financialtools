"""
run_batch_collect.py — Retrieve batch results and compile per-ticker reports
=============================================================================

Phase 2 of 2 in the batch pipeline.  Polls the OpenAI Batch job until
complete, parses the 8 topic results per ticker, writes them to the disk
cache, then calls compile_report_node to synthesise a final markdown report.

Phase 1 — download data and submit the batch — is in run_batch_submit.py.

Usage
-----
    # Poll and collect (reads batch_job.json by default)
    python scripts/run_batch_collect.py

    # Use a custom job file
    python scripts/run_batch_collect.py --job-file runs/ftse_2024.json

    # Skip compile_report step (useful if you just want topic results)
    python scripts/run_batch_collect.py --no-compile

    # Check job status without blocking
    python scripts/run_batch_collect.py --status-only

    # Recovery: job finished but script was interrupted
    python scripts/run_batch_collect.py --job-file batch_job.json

Poll interval
-------------
Default: 60 seconds.  Override with BATCH_POLL_INTERVAL env var (seconds).
For short test jobs use a smaller value, e.g. BATCH_POLL_INTERVAL=10.

Output
------
For each ticker:
    agents/.cache/{cache_key}/{topic}.json    — 8 topic result files
    agents/.cache/{cache_key}/report.md       — final compiled report (unless --no-compile)

Summary printed to stdout at the end.

Design invariants
-----------------
- custom_id format: "{cache_key}__{topic}" — same convention as run_batch_submit.py.
  cache_key uses "__" internally ({TICKER}__{year}), so parsing uses rsplit not split.
- Per-item errors in the batch response (item["error"]) are logged and the
  topic result is stored as {"error": "..."} in the cache — compile_report_node
  handles unavailable topics gracefully.
- compile_report_node is called synchronously per ticker (one LLM call each)
  after all batch results are written.  It can optionally be batched too
  (future improvement) but is cheap relative to 8 × N topic calls.
- Requires OPENAI_API_KEY in .env.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("run_batch_collect")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_JOB_FILE    = "batch_job.json"
_DEFAULT_POLL_INTERVAL = float(os.getenv("BATCH_POLL_INTERVAL", "60"))

TOPIC_NAMES: list[str] = [
    "liquidity",
    "solvency",
    "profitability",
    "efficiency",
    "cash_flow",
    "growth",
    "red_flags",
    "quantitative_overview",
]


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

def _parse_custom_id(custom_id: str) -> tuple[str, str]:
    """
    Split "cache_key__topic" into (cache_key, topic).

    Uses rsplit("__", 1) because cache_key itself contains "__" as a separator
    (e.g. "AAPL__2023__liquidity" → cache_key="AAPL__2023", topic="liquidity").
    A left-side split would give ("AAPL", "2023__liquidity") — wrong.

    Raises ValueError on malformed IDs.
    """
    parts = custom_id.rsplit("__", maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"Malformed custom_id: {custom_id!r}  (expected 'cache_key__topic')")
    return parts[0], parts[1]


def _parse_item(item: dict, topic_model_map: dict) -> tuple[str, str, dict]:
    """
    Parse one batch result item.

    Returns (cache_key, topic, result_dict) where result_dict is either the
    validated Pydantic model dict or {"error": "..."} on failure.

    Never raises — errors are captured in result_dict.
    """
    custom_id = item.get("custom_id", "")

    try:
        cache_key, topic = _parse_custom_id(custom_id)
    except ValueError as exc:
        logger.warning("Skipping item with bad custom_id %r: %s", custom_id, exc)
        return "", "", {}

    # Per-item API error (quota, bad input, etc.)
    if item.get("error"):
        err = item["error"]
        logger.warning("[%s][%s] API error: %s", cache_key, topic, err)
        return cache_key, topic, {"error": str(err)}

    try:
        content = item["response"]["body"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("[%s][%s] unexpected response shape: %s", cache_key, topic, exc)
        return cache_key, topic, {"error": f"unexpected response shape: {exc}"}

    # Validate against the Pydantic model
    model_cls = topic_model_map.get(topic)
    if model_cls is None:
        logger.warning("[%s] unknown topic %r — storing raw JSON", cache_key, topic)
        try:
            return cache_key, topic, json.loads(content)
        except json.JSONDecodeError as exc:
            return cache_key, topic, {"error": f"invalid JSON: {exc}"}

    try:
        assessment = model_cls.model_validate_json(content)
        return cache_key, topic, assessment.model_dump()
    except Exception as exc:
        logger.warning("[%s][%s] Pydantic validation failed: %s", cache_key, topic, exc)
        # Fall back to raw JSON to preserve partial data
        try:
            return cache_key, topic, json.loads(content)
        except json.JSONDecodeError:
            return cache_key, topic, {"error": f"validation failed: {exc}"}


# ---------------------------------------------------------------------------
# Cache write helpers
# ---------------------------------------------------------------------------

def _write_results_to_cache(
    results: list[dict],
    topic_model_map: dict,
) -> dict[str, dict[str, dict]]:
    """
    Parse all batch result items and write each to the disk cache.

    Returns a nested dict: {cache_key: {topic: result_dict}}.
    """
    from agents._cache import write_topic_result

    by_ticker: dict[str, dict[str, dict]] = defaultdict(dict)

    for item in results:
        cache_key, topic, result_dict = _parse_item(item, topic_model_map)
        if not cache_key or not topic:
            continue

        by_ticker[cache_key][topic] = result_dict
        write_topic_result(cache_key, topic, result_dict)
        status = "error" if "error" in result_dict else "ok"
        logger.info("[%s][%s] written to cache (%s)", cache_key, topic, status)

    return dict(by_ticker)


# ---------------------------------------------------------------------------
# Compile report phase
# ---------------------------------------------------------------------------

def _compile_reports(
    by_ticker:  dict[str, dict[str, dict]],
    job_meta:   dict,
    model:      str,
    output_dir: Path,
) -> tuple[int, int]:
    """
    Run compile_report_node for each ticker that has all 8 topic results.

    Writes report.md to agents/.cache/{cache_key}/report.md.
    Returns (success_count, skip_count).
    """
    from agents.graph_nodes import compile_report_node

    # Build a lookup: cache_key → ticker metadata
    meta_by_key = {e["cache_key"]: e for e in job_meta.get("tickers", [])}

    success = 0
    skipped = 0

    for cache_key, topics in by_ticker.items():
        # Verify all 8 topics are present (error results are still present)
        missing = [t for t in TOPIC_NAMES if t not in topics]
        if missing:
            logger.warning(
                "[%s] skipping compile — missing topics: %s", cache_key, missing
            )
            skipped += 1
            continue

        meta = meta_by_key.get(cache_key, {})

        # Build the minimal AnalysisState that compile_report_node needs
        state = {
            "ticker":                       meta.get("ticker", cache_key),
            "company_name":                 meta.get("company_name", cache_key),
            "resolved_sector":              meta.get("sector", ""),
            "model":                        model,
            "liquidity_result":             topics.get("liquidity"),
            "solvency_result":              topics.get("solvency"),
            "profitability_result":         topics.get("profitability"),
            "efficiency_result":            topics.get("efficiency"),
            "cash_flow_result":             topics.get("cash_flow"),
            "growth_result":                topics.get("growth"),
            "red_flags_result":             topics.get("red_flags"),
            "quantitative_overview_result": topics.get("quantitative_overview"),
        }

        logger.info("[%s] compiling final report ...", cache_key)
        try:
            result = compile_report_node(state)
            report = result.get("final_report", "")
        except Exception as exc:
            logger.error("[%s] compile_report_node failed: %s", cache_key, exc)
            skipped += 1
            continue

        # Write report.md alongside the topic JSON files
        report_path = output_dir / cache_key / "report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

        logger.info("[%s] report written → %s (%d chars)", cache_key, report_path, len(report))
        success += 1

    return success, skipped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = _parse_args()

    # ── 1. Load job metadata ─────────────────────────────────────────────────
    try:
        with open(args.job_file, encoding="utf-8") as f:
            job_meta = json.load(f)
    except FileNotFoundError:
        logger.error("Job file not found: %s", args.job_file)
        return 1
    except json.JSONDecodeError as exc:
        logger.error("Invalid job file: %s", exc)
        return 1

    job_id = job_meta["job_id"]
    model  = job_meta.get("model", "gpt-4.1-nano")
    n_tickers = len(job_meta.get("tickers", []))
    expected_tasks = n_tickers * len(TOPIC_NAMES)

    logger.info("job_id=%s  model=%s  tickers=%d  expected_tasks=%d",
                job_id, model, n_tickers, expected_tasks)

    from openai import OpenAI
    from kitai.batch import check_batch_job, download_batch_results, poll_until_complete

    client = OpenAI()

    # ── 2. Status-only mode ──────────────────────────────────────────────────
    if args.status_only:
        job = check_batch_job(client, job_id)
        counts = job.get("request_counts") or {}
        print(f"Status:     {job['status']}")
        print(f"Completed:  {counts.get('completed', '—')}")
        print(f"Failed:     {counts.get('failed', '—')}")
        print(f"Processing: {counts.get('processing', '—')}")
        return 0

    # ── 3. Poll until complete ───────────────────────────────────────────────
    logger.info("Polling batch job (interval=%.0fs) ...", args.poll_interval)
    completed_ids = poll_until_complete(
        client, [job_id], poll_interval=args.poll_interval
    )

    if job_id not in completed_ids:
        job = check_batch_job(client, job_id)
        logger.error(
            "Batch job did not complete — status=%s. "
            "Re-run this script to retry, or check the OpenAI dashboard.",
            job.get("status"),
        )
        if job.get("error_file_id"):
            errors = client.files.content(job["error_file_id"]).text
            logger.error("Error file:\n%s", errors[:2000])
        return 1

    logger.info("Job completed.")

    # ── 4. Download results ──────────────────────────────────────────────────
    logger.info("Downloading results ...")
    results = download_batch_results(client, job_id)
    logger.info("  %d result items received", len(results))

    # ── 5. Build topic model map ─────────────────────────────────────────────
    from financialtools.analysis import _TOPIC_MAP
    topic_model_map = {topic: cls for topic, (_, cls) in _TOPIC_MAP.items()}

    # ── 6. Parse + write to cache ────────────────────────────────────────────
    logger.info("=== Writing topic results to cache ===")
    by_ticker = _write_results_to_cache(results, topic_model_map)

    n_ok  = sum(
        1 for t in by_ticker.values()
        for r in t.values() if "error" not in r
    )
    n_err = sum(
        1 for t in by_ticker.values()
        for r in t.values() if "error" in r
    )
    logger.info("  topic results: %d ok / %d errors", n_ok, n_err)

    # ── 7. Compile reports ───────────────────────────────────────────────────
    if args.no_compile:
        logger.info("Skipping compile_report_node (--no-compile).")
    else:
        # Locate the agents cache root (same resolution as agents/_cache.py)
        cache_root = _PROJECT_ROOT / "agents" / ".cache"
        logger.info("=== Compiling reports ===")
        compiled, skipped = _compile_reports(by_ticker, job_meta, model, cache_root)
        logger.info("  compiled: %d  skipped: %d", compiled, skipped)

    # ── 8. Print summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  Job:              {job_id}")
    print(f"  Tickers:          {n_tickers}")
    print(f"  Topic results OK: {n_ok} / {expected_tasks}")
    print(f"  Topic errors:     {n_err}")
    if not args.no_compile:
        print(f"  Reports compiled: {compiled}")
        print(f"  Reports skipped:  {skipped}")
    print("=" * 60)

    if n_err:
        print(
            f"\nWarning: {n_err} topic(s) failed. "
            "Affected reports may have gaps. Check logs for details."
        )

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Retrieve OpenAI batch results and compile per-ticker reports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--job-file",
        default=_DEFAULT_JOB_FILE,
        metavar="PATH",
        help=f"Job metadata JSON written by run_batch_submit.py (default: {_DEFAULT_JOB_FILE}).",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=_DEFAULT_POLL_INTERVAL,
        metavar="SECONDS",
        help=f"Seconds between status polls (default: {_DEFAULT_POLL_INTERVAL:.0f}). "
             "Override with BATCH_POLL_INTERVAL env var.",
    )
    p.add_argument(
        "--no-compile",
        action="store_true",
        help="Write topic results to cache but skip compile_report_node.",
    )
    p.add_argument(
        "--status-only",
        action="store_true",
        help="Print current job status and exit without collecting results.",
    )
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(main())
