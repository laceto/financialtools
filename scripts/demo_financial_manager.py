"""
demo_financial_manager.py — Usage guide for the Financial Analysis Manager
==========================================================================

Demonstrates four usage patterns for the ``create_financial_manager`` agent
(LangGraph StateGraph with 8 parallel topic subgraphs).

Modes
-----
    invoke    (default)
        Full blocking run.  Prints the synthesised ``final_report`` string.

    stream
        Streams AnalysisState after every subgraph completes so you can watch
        all eight topic analysts finish in real time.

    topics
        Full blocking run then displays every topic result dict individually,
        structured for programmatic inspection.

    subgraph
        Runs a single topic subgraph in isolation.  Useful for debugging one
        topic without running the whole pipeline.  Requires --topic.

Usage
-----
    python scripts/demo_financial_manager.py --ticker AAPL
    python scripts/demo_financial_manager.py --ticker MSFT --year 2023
    python scripts/demo_financial_manager.py --ticker TSLA --mode stream
    python scripts/demo_financial_manager.py --ticker NVDA --mode topics
    python scripts/demo_financial_manager.py --ticker AAPL --mode subgraph --topic liquidity
    python scripts/demo_financial_manager.py --ticker AAPL --model gpt-4o --mode invoke

Options
-------
    --ticker    Ticker symbol, e.g. AAPL or ENI.MI  (required)
    --sector    yfinance sectorKey, e.g. "technology" (auto-detected if omitted)
    --year      Fiscal year filter, e.g. 2023 (all years if omitted)
    --model     OpenAI model name (default: gpt-4.1-nano)
    --mode      Demo mode: invoke | stream | topics | subgraph
    --topic     Topic to run in subgraph mode:
                  liquidity | solvency | profitability | efficiency |
                  cash_flow | growth | red_flags | quantitative_overview

Architecture recap
------------------
The Financial Analysis Manager is a LangGraph StateGraph:

    START
      │
      ▼
    set_model          ← injects model name into AnalysisState
      │
      ▼
    prepare_data       ← downloads yfinance data, runs FundamentalMetricsEvaluator,
      │                  writes 5 payload JSON strings to state
      │
      ├── liquidity_analyst ──────────────────────────────────────────┐
      ├── solvency_analyst ───────────────────────────────────────────┤
      ├── profitability_analyst ──────────────────────────────────────┤
      ├── efficiency_analyst ─────────────────────────────────────────┤  (parallel)
      ├── cash_flow_analyst ──────────────────────────────────────────┤
      ├── growth_analyst ───────────────────────────────────────────── ┤
      ├── red_flags_analyst ────────────────────────────────────────── ┤
      └── quantitative_overview_analyst ──────────────────────────────┘
                                        │ (LangGraph waits for all 8)
                                        ▼
                                  compile_report   ← LLM synthesis → final_report
                                        │
                                        ▼
                                       END

Data flow: AnalysisState is the sole channel between nodes.
Topic subgraphs read the five ``*_json`` fields from state; the disk cache
(agents/.cache/) is a write-only observability side-effect.

Environment
-----------
Requires OPENAI_API_KEY in a .env file at the project root.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
# `agents/` is not installed as a package (pyproject.toml packages only
# `financialtools`).  When Python runs `python scripts/demo_financial_manager.py`
# it adds `scripts/` to sys.path[0], leaving the project root absent.
# Insert the project root so that `import agents` resolves correctly.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

# Reconfigure stdout/stderr to UTF-8 on Windows so box-drawing characters
# in section headers don't raise UnicodeEncodeError (caught as ValueError).
import sys as _sys
for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Logging: INFO to stderr so stdout stays clean for report output
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("demo_financial_manager")

# Topic names in execution order — mirrors TOPIC_NAMES in agents/_subagents.py
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

_SEP  = "─" * 72
_DSEP = "═" * 72


def _section(title: str) -> str:
    return f"\n{_DSEP}\n  {title}\n{_DSEP}"


def _sub(title: str) -> str:
    return f"\n{_SEP}\n  {title}\n{_SEP}"


def _save_report(ticker: str, report: str, output_dir: str | None = None) -> Path:
    """Write *report* to ``{ticker}.md`` inside *output_dir* (default: CWD)."""
    folder = Path(output_dir) if output_dir else Path(".")
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{ticker}.md"
    out.write_text(report, encoding="utf-8")
    logger.info("Report saved → %s", out.resolve())
    return out


# ---------------------------------------------------------------------------
# Mode 1: invoke — blocking, print final_report
# ---------------------------------------------------------------------------

def demo_invoke(ticker: str, sector: str | None, year: int | None, model: str, output_dir: str | None = None) -> None:
    """
    Simplest usage pattern.

    The agent runs to completion before returning.  All 8 topic subgraphs
    execute in parallel internally; you only receive the final synthesised report.

    Invariant: result["final_report"] is always present if the graph succeeds;
    ValueError is raised if data download/evaluation fails (prepare_data_node).
    """
    from agents import create_financial_manager

    print(_section(f"MODE: invoke  |  ticker={ticker}  year={year or 'all'}  model={model}"))
    print("  Blocking run — waiting for all 8 subgraphs + compile_report ...\n")

    agent  = create_financial_manager(model=model)
    config = {"configurable": {"thread_id": f"demo-invoke-{uuid.uuid4().hex[:8]}"}}

    result = agent.invoke(
        {"ticker": ticker, "sector": sector, "year": year},
        config=config,
    )

    print(_sub("Final Report"))
    print(result["final_report"])
    _save_report(ticker, result["final_report"], output_dir)
    print(f"\n{_DSEP}\n")


# ---------------------------------------------------------------------------
# Mode 2: stream — observe each subagent as it completes
# ---------------------------------------------------------------------------

def demo_stream(ticker: str, sector: str | None, year: int | None, model: str, output_dir: str | None = None) -> None:
    """
    Streaming usage pattern.

    agent.stream() with stream_mode="values" yields the full AnalysisState
    after every node completes.  We diff successive states to show which
    topic subgraph just finished and what rating/severity it assigned.

    This is the recommended pattern for UIs or progress displays — each chunk
    is a complete, usable state snapshot, not just a delta.

    Debugging value: if a subgraph never yields its chunk, the state key it
    should write (e.g. "liquidity_result") will be absent or None.
    """
    from agents import create_financial_manager

    print(_section(f"MODE: stream  |  ticker={ticker}  year={year or 'all'}  model={model}"))
    print("  Streaming state updates — each line appears as a subgraph completes.\n")

    agent  = create_financial_manager(model=model)
    config = {"configurable": {"thread_id": f"demo-stream-{uuid.uuid4().hex[:8]}"}}

    # Track which topic keys have appeared so we can announce new completions.
    seen_topics: set[str] = set()
    final_state: dict[str, Any] = {}

    for chunk in agent.stream(
        {"ticker": ticker, "sector": sector, "year": year},
        config=config,
        stream_mode="values",
    ):
        final_state = chunk

        # Announce prepare_data completion once company_name appears.
        if "company_name" in chunk and "prepare_data" not in seen_topics:
            seen_topics.add("prepare_data")
            print(f"  [prepare_data]  company={chunk.get('company_name')}  "
                  f"sector={chunk.get('resolved_sector')}")

        # Announce each topic as its result key materialises.
        for topic in TOPIC_NAMES:
            key = f"{topic}_result"
            if key in chunk and chunk[key] and topic not in seen_topics:
                seen_topics.add(topic)
                res = chunk[key]
                label = (
                    res.get("rating")
                    or res.get("trajectory")
                    or res.get("severity")
                    or res.get("overall_rating")
                    or "?"
                )
                print(f"  [{topic}_analyst]  → {label.upper()}")

        # Announce compile_report completion.
        if "final_report" in chunk and "compile_report" not in seen_topics:
            seen_topics.add("compile_report")
            print("  [compile_report]  → report ready")

    print(_sub("Final Report (from last stream chunk)"))
    final_report = final_state.get("final_report", "")
    print(final_report or "[no final_report in state]")
    if final_report:
        _save_report(ticker, final_report, output_dir)
    print(f"\n{_DSEP}\n")


# ---------------------------------------------------------------------------
# Mode 3: topics — inspect every topic result dict individually
# ---------------------------------------------------------------------------

def demo_topics(ticker: str, sector: str | None, year: int | None, model: str, output_dir: str | None = None) -> None:
    """
    Programmatic inspection of individual topic results.

    After the agent finishes, each ``{topic}_result`` in AnalysisState is a
    Python dict with structured fields (rating, rationale, concerns, etc.).
    This mode prints each dict so you can see the raw model output before
    compile_report synthesises them.

    Useful for:
    - Validating LLM output schema for a topic
    - Diagnosing why compile_report produced a weak or incorrect summary
    - Extracting a specific field (e.g. all "concerns") across topics
    """
    from agents import create_financial_manager

    print(_section(f"MODE: topics  |  ticker={ticker}  year={year or 'all'}  model={model}"))
    print("  Full run then per-topic result inspection.\n")

    agent  = create_financial_manager(model=model)
    config = {"configurable": {"thread_id": f"demo-topics-{uuid.uuid4().hex[:8]}"}}

    result = agent.invoke(
        {"ticker": ticker, "sector": sector, "year": year},
        config=config,
    )

    # ── Per-topic structured output ───────────────────────────────────────────
    topic_labels = {
        "liquidity":             ("1/8", "rating"),
        "solvency":              ("2/8", "rating"),
        "profitability":         ("3/8", "rating"),
        "efficiency":            ("4/8", "rating"),
        "cash_flow":             ("5/8", "rating"),
        "growth":                ("6/8", "trajectory"),
        "red_flags":             ("7/8", "severity"),
        "quantitative_overview": ("8/8", "overall_rating"),
    }

    for topic, (num, label_key) in topic_labels.items():
        key = f"{topic}_result"
        res = result.get(key)

        print(_sub(f"{num}  {topic.upper()}"))

        if not res:
            print("  [result missing — subgraph may have failed]")
            continue
        if "error" in res:
            print(f"  [error] {res['error']}")
            continue

        # Primary label
        label_val = res.get(label_key, "—")
        print(f"  {label_key:<28}: {str(label_val).upper()}")

        # Rationale
        if res.get("rationale"):
            print(f"  {'rationale':<28}: {res['rationale']}")

        # Remaining structured fields (skip already-shown keys)
        skip = {label_key, "rationale"}
        for field, val in res.items():
            if field in skip or not val:
                continue
            # Truncate long strings for readability
            display = str(val)
            if len(display) > 200:
                display = display[:197] + "..."
            print(f"  {field:<28}: {display}")

    # ── Final synthesised report ──────────────────────────────────────────────
    print(_section("SYNTHESISED REPORT (compile_report output)"))
    final_report = result.get("final_report", "")
    print(final_report or "[no final_report]")
    if final_report:
        _save_report(ticker, final_report, output_dir)
    print(f"\n{_DSEP}\n")


# ---------------------------------------------------------------------------
# Mode 4: subgraph — run a single topic subgraph in isolation
# ---------------------------------------------------------------------------

def demo_subgraph(
    ticker: str,
    sector: str | None,
    year: int | None,
    model: str,
    topic: str,
) -> None:
    """
    Isolated single-topic subgraph run.

    This demonstrates how topic subgraphs can be invoked independently of the
    full manager graph.  It mirrors exactly what the manager does internally:

        1. Call _download_and_evaluate() to populate the five *_json payload
           fields that the subgraph reads from state.
        2. Invoke the compiled subgraph with the state dict.
        3. Read back the {topic}_result.

    Invariants:
    - Subgraphs are stateless — they only need the *_json fields in state.
    - This path still writes the disk cache (observability side-effect).
    - The @tool wrappers (run_*_analysis) take a different path (disk cache)
      and exist for backward compatibility; this demo shows the graph path.

    Debugging: if the subgraph returns {"error": ...}, check the raw LLM
    output in logs/debug.log.  The one-shot retry inside _analyse_topic will
    also be visible there.
    """
    from agents._subagents import build_topic_subgraphs
    from agents._tools.data_tools import _download_and_evaluate

    if topic not in TOPIC_NAMES:
        print(f"Error: unknown topic '{topic}'. Choose from: {', '.join(TOPIC_NAMES)}",
              file=sys.stderr)
        sys.exit(1)

    print(_section(f"MODE: subgraph  |  topic={topic}  ticker={ticker}  model={model}"))

    # ── Step 1: Prepare data (same as prepare_data_node) ─────────────────────
    print("  Step 1/2 — downloading and evaluating data ...")
    payloads = _download_and_evaluate(ticker, sector, year)
    print(f"  company={payloads['company_name']}  sector={payloads['sector']}  "
          f"cache_key={payloads['cache_key']}\n")

    # ── Step 2: Build and invoke the topic subgraph ───────────────────────────
    print(f"  Step 2/2 — invoking {topic}_analyst subgraph ...")

    subgraphs = build_topic_subgraphs()
    subgraph  = subgraphs[topic]

    # Construct a minimal AnalysisState — exactly what the manager passes.
    state = {
        "ticker":                 ticker,
        "sector":                 payloads["sector"],
        "year":                   year,
        "model":                  model,
        "cache_key":              payloads["cache_key"],
        "company_name":           payloads["company_name"],
        "resolved_sector":        payloads["sector"],
        "metrics_json":           payloads["metrics_json"],
        "extended_metrics_json":  payloads["extended_metrics_json"],
        "eval_metrics_json":      payloads["eval_metrics_json"],
        "composite_scores_json":  payloads["composite_scores_json"],
        "red_flags_json":         payloads["red_flags_json"],
    }

    result = subgraph.invoke(state)

    # ── Display result ────────────────────────────────────────────────────────
    topic_result = result.get(f"{topic}_result")
    print(_sub(f"Result: {topic}_result"))

    if not topic_result:
        print("  [result missing — check logs]")
    elif "error" in topic_result:
        print(f"  [error] {topic_result['error']}")
    else:
        print(json.dumps(topic_result, indent=2))

    print(f"\n{_DSEP}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Demo script for the Financial Analysis Manager (LangGraph StateGraph).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--ticker",  required=True,            metavar="SYMBOL",
                   help="Ticker symbol, e.g. AAPL or ENI.MI")
    p.add_argument("--sector",  default=None,             metavar="SECTOR",
                   help="yfinance sectorKey (auto-detected if omitted)")
    p.add_argument("--year",    type=int, default=None,   metavar="YEAR",
                   help="Fiscal year filter, e.g. 2023")
    p.add_argument("--model",   default="gpt-4.1-nano",   metavar="MODEL",
                   help="OpenAI model (default: gpt-4.1-nano)")
    p.add_argument("--mode",
                   choices=["invoke", "stream", "topics", "subgraph"],
                   default="invoke",
                   help="Demo mode (default: invoke)")
    p.add_argument("--topic",
                   choices=TOPIC_NAMES,
                   default=None,
                   metavar="TOPIC",
                   help=f"Topic for --mode subgraph. One of: {', '.join(TOPIC_NAMES)}")
    p.add_argument("--output-dir", default=None, metavar="DIR",
                   help="Directory to save {ticker}.md (default: current directory)")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    if args.mode == "subgraph" and args.topic is None:
        print("Error: --topic is required when --mode subgraph is used.", file=sys.stderr)
        print(f"  Valid topics: {', '.join(TOPIC_NAMES)}", file=sys.stderr)
        return 1

    try:
        if args.mode == "invoke":
            demo_invoke(args.ticker, args.sector, args.year, args.model, args.output_dir)
        elif args.mode == "stream":
            demo_stream(args.ticker, args.sector, args.year, args.model, args.output_dir)
        elif args.mode == "topics":
            demo_topics(args.ticker, args.sector, args.year, args.model, args.output_dir)
        elif args.mode == "subgraph":
            demo_subgraph(args.ticker, args.sector, args.year, args.model, args.topic)
    except ValueError as exc:
        logger.error("Data preparation failed: %s", exc)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
