"""
run_batch_submit.py — Submit FTSE MIB (or any index) topic analysis as an OpenAI Batch job
============================================================================================

Phase 1 of 2 in the batch pipeline.  Downloads financial data for every ticker,
builds 8 LLM topic-analysis prompts per ticker, and submits them all as a single
OpenAI Batch API job (50% cheaper than synchronous calls).

Phase 2 — collect results and compile reports — is in run_batch_collect.py.

Usage
-----
    # Full run: download + submit for FTSE MIB
    python scripts/run_batch_submit.py

    # Custom ticker file
    python scripts/run_batch_submit.py --tickers my_tickers.txt

    # Filter to a single fiscal year
    python scripts/run_batch_submit.py --year 2023

    # Skip re-downloading tickers whose payloads.json already exists in cache
    python scripts/run_batch_submit.py --skip-download

    # Use a cheaper/faster model for the topic prompts
    python scripts/run_batch_submit.py --model gpt-4.1-mini

    # Write job metadata to a custom path (default: batch_job.json)
    python scripts/run_batch_submit.py --job-file runs/ftse_2024.json

Ticker file format
------------------
Tab-separated, columns: ticker  sector
Sector must match a key in config.sec_sector_metric_weights
(e.g. "technology", "financial-services", "utilities").

Output
------
Writes --job-file (default: batch_job.json) — a JSON document with:
    {
        "job_id":  "batch_abc123",
        "model":   "gpt-4.1-nano",
        "year":    null,
        "tickers": [
            {"ticker": "ENI.MI", "cache_key": "ENI.MI_all",
             "company_name": "eni s.p.a.", "sector": "energy"},
            ...
        ]
    }

Pass this file to run_batch_collect.py to retrieve results.

Design invariants
-----------------
- Download is sequential — yfinance rate-limits concurrent requests.
- One JSONL batch job for all tickers × 8 topics.
- custom_id format: "{cache_key}__{topic}" — the topic is appended with "__"
  after the cache_key; the cache_key itself also uses "__" as its separator
  ({TICKER}__{year}), so parse with rsplit("__", 1) not split.
- system prompts are filled with format_instructions="" because the response
  format is enforced by the API-level response_format parameter (strict mode).
- Per-ticker download failures are logged and skipped; the remaining tickers
  are still submitted.
- Requires OPENAI_API_KEY in .env.

Environment
-----------
OPENAI_API_KEY  — required
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Path bootstrap — agents/ is not an installed package
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
logger = logging.getLogger("run_batch_submit")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_TICKERS = str(
    _PROJECT_ROOT / "financialtools" / "data" / "ftse_mib.txt"
)
_DEFAULT_JOB_FILE = "batch_job.json"
_DEFAULT_MODEL    = "gpt-4.1-nano"
_DOWNLOAD_SLEEP   = 2.0   # seconds between yfinance downloads (rate-limit guard)

# ---------------------------------------------------------------------------
# Topic order — mirrors agents/_subagents.py TOPIC_NAMES
# ---------------------------------------------------------------------------
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
# Strict-mode schema helpers (required by OpenAI structured output)
# ---------------------------------------------------------------------------

def _strict_in_place(node: dict) -> None:
    """
    Transform a Pydantic model_json_schema() into an OpenAI strict-mode schema.

    Strict mode requires:
    - additionalProperties: false on every object
    - all properties listed in required
    - $ref nodes must have no sibling keys

    Modifies node in-place — call on a deep copy.
    """
    if not isinstance(node, dict):
        return
    if "$ref" in node:
        # OpenAI strict: $ref must be the ONLY key in its node.
        for k in list(node.keys()):
            if k != "$ref":
                del node[k]
        return
    if node.get("type") == "object" or "properties" in node:
        node["additionalProperties"] = False
        if "properties" in node:
            node["required"] = list(node["properties"].keys())
            for child in node["properties"].values():
                _strict_in_place(child)
    for sub in node.get("$defs", {}).values():
        _strict_in_place(sub)
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in node.get(key, []):
            _strict_in_place(sub)
    if "items" in node:
        _strict_in_place(node["items"])


def _response_format(model_cls: type) -> dict:
    """Build a strict response_format dict for a Pydantic model."""
    schema = copy.deepcopy(model_cls.model_json_schema())
    _strict_in_place(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name":   model_cls.__name__,
            "schema": schema,
            "strict": True,
        },
    }


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _build_messages(system_prompt_str: str, payloads: dict) -> list[dict]:
    """
    Build the messages list for one topic request.

    system_prompt_str has a {format_instructions} placeholder — we pass ""
    because the output format is enforced by response_format (strict mode).
    The human message matches the _TOPIC_HUMAN_TEMPLATE used by _analyse_topic.
    """
    system = system_prompt_str.format(format_instructions="")
    human  = (
        f"Metrics:\n{payloads['metrics']}\n"
        f"Extended Metrics:\n{payloads['extended_metrics']}\n"
        f"Scores:\n{payloads['composite_scores']}\n"
        f"Evaluation Metrics:\n{payloads['eval_metrics']}\n"
        f"RedFlags:\n{payloads['red_flags']}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": human},
    ]


def _build_task(
    cache_key: str,
    topic:     str,
    payloads:  dict,
    model:     str,
    model_cls: type,
) -> dict:
    """
    Build one Batch API task dict for (cache_key, topic).

    custom_id format: "{cache_key}__{topic}"
    Parse with rsplit("__", 1) — cache_key itself contains "__" ({TICKER}__{year}).
    """
    from financialtools.analysis import _TOPIC_MAP

    system_prompt_str, _ = _TOPIC_MAP[topic]
    messages = _build_messages(system_prompt_str, payloads)

    return {
        "custom_id": f"{cache_key}__{topic}",
        "method":    "POST",
        "url":       "/v1/chat/completions",
        "body": {
            "model":           model,
            "max_tokens":      1024,
            "messages":        messages,
            "response_format": _response_format(model_cls),
        },
    }


# ---------------------------------------------------------------------------
# Ticker file reader
# ---------------------------------------------------------------------------

def _load_tickers(filepath: str) -> list[dict]:
    """
    Load a tab-separated ticker file (columns: ticker, sector).

    Returns list of {"ticker": str, "sector": str}.
    Extra columns are ignored.  Blank lines and comments (#) are skipped.
    """
    import pandas as pd

    df = pd.read_csv(filepath, sep="\t", comment="#", dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]

    if "ticker" not in df.columns:
        raise ValueError(f"Ticker file {filepath!r} must have a 'ticker' column.")
    if "sector" not in df.columns:
        logger.warning("No 'sector' column in %s — sector will be auto-detected.", filepath)
        df["sector"] = None

    df = df[["ticker", "sector"]].dropna(subset=["ticker"])
    df["ticker"] = df["ticker"].str.strip()
    df["sector"] = df["sector"].str.strip() if "sector" in df.columns else None

    return df.to_dict("records")


# ---------------------------------------------------------------------------
# Download phase
# ---------------------------------------------------------------------------

def _download_all(
    ticker_rows: list[dict],
    year: int | None,
    skip_if_cached: bool,
) -> list[dict]:
    """
    Download and evaluate data for every ticker.

    Returns a list of enriched dicts (adds cache_key, company_name, payloads).
    Tickers that fail are logged and excluded from the returned list.
    """
    from agents._cache import cache_key as make_cache_key
    from agents._tools.data_tools import _download_and_evaluate
    from agents._cache import read_payloads

    results: list[dict] = []

    for i, row in enumerate(ticker_rows, start=1):
        ticker = row["ticker"]
        sector = row.get("sector") or None
        key    = make_cache_key(ticker, year)

        logger.info("[%d/%d] %s", i, len(ticker_rows), ticker)

        # Optional: reuse existing cache to avoid re-downloading
        if skip_if_cached:
            try:
                existing = read_payloads(key)
                logger.info("  cache hit — skipping download for %s", key)
                results.append({
                    "ticker":       ticker,
                    "sector":       existing.get("sector", sector),
                    "cache_key":    key,
                    "company_name": existing.get("company_name", ticker.lower()),
                    "payloads":     existing,
                })
                continue
            except FileNotFoundError:
                pass  # fall through to download

        try:
            data = _download_and_evaluate(ticker, sector, year)
            results.append({
                "ticker":       ticker,
                "sector":       data["sector"],
                "cache_key":    data["cache_key"],
                "company_name": data["company_name"],
                "payloads": {
                    "ticker":           ticker,
                    "metrics":          data["metrics_json"],
                    "extended_metrics": data["extended_metrics_json"],
                    "composite_scores": data["composite_scores_json"],
                    "eval_metrics":     data["eval_metrics_json"],
                    "red_flags":        data["red_flags_json"],
                },
            })
            logger.info("  OK — cache_key=%s company=%s", data["cache_key"], data["company_name"])
        except Exception as exc:
            logger.error("  FAILED %s: %s", ticker, exc)

        # Rate-limit guard — yfinance throttles concurrent/rapid requests
        if i < len(ticker_rows):
            time.sleep(_DOWNLOAD_SLEEP)

    return results


# ---------------------------------------------------------------------------
# Batch task builder
# ---------------------------------------------------------------------------

def _build_all_tasks(
    downloaded: list[dict],
    model:      str,
) -> list[dict]:
    """
    Build one Batch API task per (ticker, topic) pair.

    Returns the full list of task dicts ready for submit_batch_job().
    """
    from financialtools.analysis import _TOPIC_MAP

    tasks: list[dict] = []

    for entry in downloaded:
        cache_key = entry["cache_key"]
        payloads  = entry["payloads"]

        for topic in TOPIC_NAMES:
            _, model_cls = _TOPIC_MAP[topic]
            task = _build_task(cache_key, topic, payloads, model, model_cls)
            tasks.append(task)

    return tasks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = _parse_args()

    # ── 1. Load ticker list ──────────────────────────────────────────────────
    logger.info("Loading tickers from %s", args.tickers)
    try:
        ticker_rows = _load_tickers(args.tickers)
    except Exception as exc:
        logger.error("Failed to load ticker file: %s", exc)
        return 1

    logger.info("  %d tickers loaded", len(ticker_rows))

    # ── 2. Download + evaluate ───────────────────────────────────────────────
    logger.info("=== PHASE 1: download + evaluate ===")
    downloaded = _download_all(ticker_rows, args.year, args.skip_download)

    if not downloaded:
        logger.error("No tickers downloaded successfully — nothing to submit.")
        return 1

    logger.info("%d / %d tickers downloaded OK", len(downloaded), len(ticker_rows))

    # ── 3. Build batch tasks ─────────────────────────────────────────────────
    logger.info("=== PHASE 2: building batch tasks ===")
    tasks = _build_all_tasks(downloaded, args.model)
    logger.info(
        "  %d tasks built (%d tickers × %d topics)",
        len(tasks), len(downloaded), len(TOPIC_NAMES),
    )

    # ── 4. Submit ────────────────────────────────────────────────────────────
    logger.info("=== PHASE 3: submitting batch job ===")

    from openai import OpenAI
    from kitai.batch import submit_batch_job

    client = OpenAI()

    try:
        job_id = submit_batch_job(
            client,
            tasks,
            endpoint="/v1/chat/completions",
            metadata={"description": f"financialtools topic analysis — {len(downloaded)} tickers"},
        )
    except Exception as exc:
        logger.error("Batch submission failed: %s", exc)
        return 1

    logger.info("  job_id = %s", job_id)
    print(f"\nBatch job submitted: {job_id}")
    print(f"Tasks: {len(tasks)} ({len(downloaded)} tickers × {len(TOPIC_NAMES)} topics)")

    # ── 5. Save job metadata ─────────────────────────────────────────────────
    job_meta = {
        "job_id": job_id,
        "model":  args.model,
        "year":   args.year,
        "tickers": [
            {
                "ticker":       e["ticker"],
                "cache_key":    e["cache_key"],
                "company_name": e["company_name"],
                "sector":       e["sector"],
            }
            for e in downloaded
        ],
    }

    with open(args.job_file, "w", encoding="utf-8") as f:
        json.dump(job_meta, f, indent=2)

    print(f"Job metadata saved to: {args.job_file}")
    print(f"\nRun next step when complete:\n  python scripts/run_batch_collect.py --job-file {args.job_file}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Submit FTSE MIB (or any index) topic analysis as an OpenAI Batch job.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--tickers",
        default=_DEFAULT_TICKERS,
        metavar="FILE",
        help=f"Tab-separated ticker file (default: ftse_mib.txt). Columns: ticker, sector.",
    )
    p.add_argument(
        "--year",
        type=int,
        default=None,
        metavar="YEAR",
        help="Fiscal year filter, e.g. 2023. Omit for all available years.",
    )
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        metavar="MODEL",
        help=f"OpenAI model for topic analysis (default: {_DEFAULT_MODEL}).",
    )
    p.add_argument(
        "--job-file",
        default=_DEFAULT_JOB_FILE,
        metavar="PATH",
        help=f"Output path for job metadata JSON (default: {_DEFAULT_JOB_FILE}).",
    )
    p.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse existing agents/.cache payloads instead of re-downloading.",
    )
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(main())
