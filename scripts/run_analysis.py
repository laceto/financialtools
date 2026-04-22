"""
run_analysis.py — CLI for single-ticker topic analysis
=======================================================

Downloads yfinance data, computes 24 scored + 14 extended metrics, then
calls nine LLM chains (eight topic models + StockRegimeAssessment) and
prints a structured report.

Usage
-----
    python scripts/run_analysis.py --ticker AAPL --sector technology
    python scripts/run_analysis.py --ticker ENI.MI --sector energy --year 2023
    python scripts/run_analysis.py --ticker AAPL --sector technology --model gpt-4o
    python scripts/run_analysis.py --list-sectors

Options
-------
    --ticker      Ticker symbol (required unless --list-sectors)
    --sector      Sector name matching config.sec_sector_metric_weights
                  (required unless --list-sectors)
    --year        Optional year filter; omit to include all available years
    --model       OpenAI model name (default: gpt-4.1-nano)
    --list-sectors  Print all valid sector names and exit

Output
------
Prints a structured text report to stdout. Each topic section shows the
classification label (rating / trajectory / severity) and the LLM rationale.
The final section shows the overall regime and valuation classification.

Environment
-----------
Requires OPENAI_API_KEY in a .env file at the project root, or set in the
environment. LangSmith tracing is enabled automatically if LANGSMITH_API_KEY
is also set.

Exit codes
----------
0 — success
1 — invalid arguments or EvaluationError (download / evaluation failure)
"""

import argparse
import logging
import sys

from financialtools.config import sec_sector_metric_weights

# ---------------------------------------------------------------------------
# Logging: console output for the script; wrappers.py configures file handlers
# ---------------------------------------------------------------------------
_console = logging.StreamHandler()
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

_root = logging.getLogger()
_root.setLevel(logging.INFO)
_root.addHandler(_console)

logger = logging.getLogger("run_analysis")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_SEPARATOR = "─" * 72
_SECTION = "═" * 72


def _section(title: str) -> str:
    return f"\n{_SECTION}\n  {title}\n{_SECTION}"


def _sub(title: str) -> str:
    return f"\n{_SEPARATOR}\n  {title}\n{_SEPARATOR}"


def _field(label: str, value) -> str:
    return f"  {label:<22}: {value}"


def _optional(label: str, value) -> str:
    if value:
        return f"  {label:<22}: {value}"
    return ""


def _print_report(result) -> None:
    """Print a human-readable report for a TopicAnalysisResult."""
    print(_section(f"FUNDAMENTAL ANALYSIS — {result.ticker}"))
    print(_field("Sector", result.sector))
    if result.year:
        print(_field("Year filter", result.year))

    # ------------------------------------------------------------------
    # Liquidity
    # ------------------------------------------------------------------
    print(_sub("1 / 8  Liquidity"))
    if result.liquidity:
        a = result.liquidity
        print(_field("Rating", a.rating.upper()))
        print(_field("Rationale", a.rationale))
        print(_field("WC Efficiency", a.working_capital_efficiency))
        print(_optional("Concerns", a.concerns))
    else:
        print("  [chain failed — see logs]")

    # ------------------------------------------------------------------
    # Solvency
    # ------------------------------------------------------------------
    print(_sub("2 / 8  Solvency"))
    if result.solvency:
        a = result.solvency
        print(_field("Rating", a.rating.upper()))
        print(_field("Rationale", a.rationale))
        print(_field("Debt Trend", a.debt_trend))
        print(_optional("Concerns", a.concerns))
    else:
        print("  [chain failed — see logs]")

    # ------------------------------------------------------------------
    # Profitability
    # ------------------------------------------------------------------
    print(_sub("3 / 8  Profitability"))
    if result.profitability:
        a = result.profitability
        print(_field("Rating", a.rating.upper()))
        print(_field("Rationale", a.rationale))
        print(_field("Earnings Quality", a.earnings_quality))
        print(_optional("Concerns", a.concerns))
    else:
        print("  [chain failed — see logs]")

    # ------------------------------------------------------------------
    # Efficiency
    # ------------------------------------------------------------------
    print(_sub("4 / 8  Efficiency"))
    if result.efficiency:
        a = result.efficiency
        print(_field("Rating", a.rating.upper()))
        print(_field("Rationale", a.rationale))
        print(_field("WC Chain", a.working_capital_chain))
        print(_optional("Concerns", a.concerns))
    else:
        print("  [chain failed — see logs]")

    # ------------------------------------------------------------------
    # Cash Flow
    # ------------------------------------------------------------------
    print(_sub("5 / 8  Cash Flow"))
    if result.cash_flow:
        a = result.cash_flow
        print(_field("Rating", a.rating.upper()))
        print(_field("Rationale", a.rationale))
        print(_field("Capital Allocation", a.capital_allocation))
        print(_optional("Concerns", a.concerns))
    else:
        print("  [chain failed — see logs]")

    # ------------------------------------------------------------------
    # Growth
    # ------------------------------------------------------------------
    print(_sub("6 / 8  Growth"))
    if result.growth:
        a = result.growth
        print(_field("Trajectory", a.trajectory.upper()))
        print(_field("Rationale", a.rationale))
        print(_field("Dilution Impact", a.dilution_impact))
        print(_optional("Concerns", a.concerns))
    else:
        print("  [chain failed — see logs]")

    # ------------------------------------------------------------------
    # Red Flags
    # ------------------------------------------------------------------
    print(_sub("7 / 8  Red Flags"))
    if result.red_flags:
        a = result.red_flags
        print(_field("Severity", a.severity.upper()))
        print(_field("Rationale", a.rationale))
        print(_optional("Cash Flow Flags", a.cash_flow_flags))
        print(_optional("Threshold Flags", a.threshold_flags))
        print(_optional("Quality Concerns", a.quality_concerns))
    else:
        print("  [chain failed — see logs]")

    # ------------------------------------------------------------------
    # Quantitative Overview
    # ------------------------------------------------------------------
    print(_sub("8 / 8  Quantitative Overview"))
    if result.quantitative_overview:
        a = result.quantitative_overview
        print(_field("Overall Rating", a.overall_rating.upper()))
        print(_field("Composite Trend", a.composite_trend.upper()))
        print(_field("Trend Rationale", a.composite_trend_rationale))
        print(_field("Scoring Profile", a.scoring_profile))
        print(_field("Valuation Context", a.valuation_context))
        print(_field("Cross-dim Signals", a.cross_dimensional_signals))
        print(_field("Data Completeness", a.data_completeness.upper()))
        print(_optional("Concerns", a.concerns))
    else:
        print("  [chain failed — see logs]")

    # ------------------------------------------------------------------
    # Overall Regime
    # ------------------------------------------------------------------
    print(_section("OVERALL ASSESSMENT"))
    if result.regime:
        r = result.regime
        print(_field("Regime", r.regime.upper()))
        print(_field("Regime Rationale", r.regime_rationale))
        print(_field("Evaluation", r.evaluation.upper()))
        print(_field("Eval Rationale", r.evaluation_rationale))
        print(_field("Metrics Movement", r.metrics_movement))
        if r.non_aligned_findings:
            print(_field("Non-aligned", r.non_aligned_findings))
        print(_field("Market Comparison", r.market_comparison))
    else:
        print("  [regime chain failed — see logs]")

    print(f"\n{_SECTION}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run fundamental topic analysis for a single ticker.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--ticker",
        metavar="SYMBOL",
        help="Ticker symbol, e.g. AAPL or ENI.MI",
    )
    p.add_argument(
        "--sector",
        metavar="SECTOR",
        help=(
            "Sector name from config.sec_sector_metric_weights, e.g. 'technology'. "
            "Run --list-sectors to see all valid values."
        ),
    )
    p.add_argument(
        "--year",
        type=int,
        default=None,
        metavar="YEAR",
        help="Optional year filter (e.g. 2023). Omit to analyse all years.",
    )
    p.add_argument(
        "--model",
        default="gpt-4.1-nano",
        metavar="MODEL",
        help="OpenAI model name (default: gpt-4.1-nano)",
    )
    p.add_argument(
        "--list-sectors",
        action="store_true",
        help="Print all valid sector names and exit.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    if args.list_sectors:
        print("Valid sector names:")
        for s in sorted(sec_sector_metric_weights.keys()):
            print(f"  {s}")
        return 0

    if not args.ticker:
        print("Error: --ticker is required.", file=sys.stderr)
        return 1
    if not args.sector:
        print("Error: --sector is required.", file=sys.stderr)
        return 1

    from financialtools.analysis import run_topic_analysis
    from financialtools.exceptions import EvaluationError

    try:
        result = run_topic_analysis(
            ticker=args.ticker,
            sector=args.sector,
            year=args.year,
            model=args.model,
        )
    except EvaluationError as exc:
        logger.error("Evaluation failed: %s", exc)
        return 1
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        return 1

    _print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
