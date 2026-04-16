"""
agents/_cache.py — Disk-based payload cache for the financial analysis agent.

Purpose
-------
The manager agent downloads and evaluates financial data once per ticker/year
request, then serialises the five LLM input payloads to disk.  Topic subagents
read the cache and only run their own LLM chain — no redundant yfinance calls.

Cache layout
------------
agents/.cache/
└── {ticker}_{year}/
    ├── payloads.json      # five JSON payloads + metadata (written by manager)
    └── {topic}.json       # topic assessment result (written by subagent)

Public API
----------
cache_key(ticker, year)              → str
clear_cache(key)                     → None
write_payloads(key, data)            → None
read_payloads(key)                   → dict
write_topic_result(key, topic, data) → None
read_topic_result(key, topic)        → dict | None

Design invariants
-----------------
- All I/O errors surface as exceptions — callers decide how to handle.
- Cache keys are filesystem-safe: uppercase tickers, "all" when year is None.
- Cache dir is resolved relative to this file's location (not cwd).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any

_logger = logging.getLogger(__name__)

# ─── Cache root: agents/.cache/ relative to this file ────────────────────────
_CACHE_ROOT = os.path.join(os.path.dirname(__file__), ".cache")


def cache_key(ticker: str, year: int | None) -> str:
    """
    Build a filesystem-safe cache key for a ticker + optional year.

    Examples
    --------
    cache_key("AAPL", 2023) → "AAPL_2023"
    cache_key("eni.mi", None) → "ENI.MI_all"
    """
    return f"{ticker.upper()}_{year if year is not None else 'all'}"


def _cache_dir(key: str) -> str:
    """Return the absolute directory path for a given cache key (creates it)."""
    path = os.path.join(_CACHE_ROOT, key)
    os.makedirs(path, exist_ok=True)
    return path


def clear_cache(key: str) -> None:
    """
    Delete all cached files for a given cache key.

    Removes the entire directory at ``_CACHE_ROOT/{key}/``, including
    ``payloads.json`` and any ``{topic}.json`` files written by previous runs.
    No-op if the directory does not exist.

    Called by ``_download_and_evaluate`` when ``force_refresh=True`` so that
    a full re-download replaces every stale artefact — not just payloads.

    Parameters
    ----------
    key : Cache key, as returned by ``cache_key(ticker, year)``.
    """
    path = os.path.join(_CACHE_ROOT, key)
    if os.path.isdir(path):
        shutil.rmtree(path)
        _logger.info("[cache] cleared cache dir: %s", path)
    else:
        _logger.debug("[cache] clear_cache: directory not found, nothing to clear (%s)", path)


def write_payloads(key: str, data: dict[str, Any]) -> None:
    """
    Persist the five LLM input payloads (+ metadata) to disk.

    Expected data keys
    ------------------
    ticker, sector, year, metrics, extended_metrics,
    composite_scores, eval_metrics, red_flags
    """
    path = os.path.join(_cache_dir(key), "payloads.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def read_payloads(key: str) -> dict[str, Any]:
    """
    Load cached payloads for a cache key.

    Raises
    ------
    FileNotFoundError if the cache entry does not exist.
    """
    path = os.path.join(_CACHE_ROOT, key, "payloads.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No cached payloads for key '{key}'. "
            "Call prepare_financial_data first."
        )
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_topic_result(key: str, topic: str, data: dict[str, Any]) -> None:
    """Write a topic assessment result to the cache directory."""
    path = os.path.join(_cache_dir(key), f"{topic}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def read_topic_result(key: str, topic: str) -> dict[str, Any] | None:
    """
    Read a cached topic result.

    Returns None if the result has not been written yet (no error raised).
    """
    path = os.path.join(_CACHE_ROOT, key, f"{topic}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
