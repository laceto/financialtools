"""
tools.py — LangChain tool wrappers for the financialtools package.

Exposes five @tool functions that a LangChain / LangGraph agent can call
to discover tickers, retrieve financial metrics, sector benchmarks, red flags,
and run the full LLM regime report.

All tools are safe to call in any order.  They return JSON strings so the
agent can inspect structured data without further parsing.

Tool inventory
--------------
list_available_tickers  — discover evaluated tickers
get_stock_metrics       — raw financial + valuation metrics + composite score
get_sector_benchmarks   — peer-average metrics for a sector
get_red_flags           — warning signals for a ticker
get_stock_regime_report — full LLM regime assessment (StockRegimeAssessment)

Design invariants
-----------------
- Every tool returns a JSON string (never raises to the agent).
- Errors are returned as {"error": "<message>"} so the agent can reason about
  failures without a traceback interrupting the chain.
- File paths (base_dir, sector_file) are deployment config, not agent decisions.
  They are baked into the tools at bootstrap time via make_tools(), never
  exposed as tool parameters the LLM can set.
- Pydantic v2 serialisation uses `.model_dump()` (not `.dict()` or `.json()`).

External-consumer usage
-----------------------
    from financialtools.tools import make_tools

    tools = make_tools(
        base_dir="/path/to/my/financial_data",
        sector_file="/path/to/my/sector_ticker.txt",
    )
    agent = create_agent(model=llm, tools=tools, ...)

In-repo / default usage
-----------------------
    from financialtools.tools import TOOLS   # make_tools() with default paths

    agent = create_agent(model=llm, tools=TOOLS, ...)
"""

from __future__ import annotations

import json
import logging
import os

from langchain_core.tools import tool

from financialtools.chains import get_stock_evaluation_report
from financialtools.exceptions import SectorNotFoundError
from financialtools.utils import (
    dataframe_to_json,
    get_fin_data,
    get_market_metrics,
    list_evaluated_tickers,
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> str:
    """Serialise an error message into the standard tool error envelope."""
    return json.dumps({"error": msg})


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_tools(
    base_dir: str = "financial_data",
    sector_file: str = "financialtools/data/sector_ticker.txt",
) -> list:
    """
    Create the five agent tools with file paths baked in.

    Call this at agent bootstrap time — not at import time — so the paths
    can be set by the external consumer without monkey-patching globals.

    Args:
        base_dir:    Directory containing the evaluation output files
                     (metrics.xlsx, composite_scores.xlsx, red_flags.xlsx,
                     raw_red_flags.xlsx, eval_metrics.xlsx,
                     metrics_by_sectors.xlsx, eval_metrics_by_sectors.xlsx).
                     Defaults to "financial_data" (relative to CWD).
        sector_file: Path to the tab-separated sector mapping file
                     (columns: ticker, sector, name, marginabile).
                     External consumers should pass the path to their copy.

    Returns:
        List of five LangChain @tool objects ready to pass to create_agent().
    """

    @tool
    def list_available_tickers() -> str:
        """
        Return a JSON list of all ticker symbols that have been evaluated and are
        stored in the financial_data directory.

        Use this tool first to discover which tickers are available before calling
        get_stock_metrics, get_red_flags, or get_stock_regime_report.

        Returns:
            JSON array of ticker strings, e.g. ["AAPL", "ENI.MI", "MSFT"].
            Returns {"error": "..."} on failure.
        """
        try:
            tickers = list_evaluated_tickers(base_dir=base_dir)
            return json.dumps(tickers)
        except Exception as exc:
            _logger.error("list_available_tickers failed", exc_info=True)
            return _err(str(exc))

    @tool
    def get_stock_metrics(ticker: str, year: int | None = None) -> str:
        """
        Return financial metrics, composite score, and red flags for a ticker.

        Args:
            ticker: Ticker symbol (e.g. "AAPL", "ENI.MI").
            year:   Optional year to filter metrics to. If omitted, returns all years.

        Returns:
            JSON object with keys:
                metrics          — profitability, leverage, cash-flow metrics
                composite_scores — weighted 1–5 fundamental score per year
                red_flags        — warning signals detected for the ticker
            Returns {"error": "..."} if the ticker is not found.
        """
        try:
            metrics_json, composite_json, red_flags_json = get_fin_data(
                ticker=ticker, year=year, base_dir=base_dir
            )
            result = {
                "metrics": json.loads(metrics_json),
                "composite_scores": json.loads(composite_json),
                "red_flags": json.loads(red_flags_json),
            }
            return json.dumps(result)
        except FileNotFoundError as exc:
            return _err(f"Financial data files not found — run the pipeline first. Detail: {exc}")
        except Exception as exc:
            _logger.error("get_stock_metrics failed for %s", ticker, exc_info=True)
            return _err(str(exc))

    @tool
    def get_sector_benchmarks(sector: str) -> str:
        """
        Return peer-average financial and valuation metrics for a sector.

        These are the market benchmarks that chains.py uses to contextualise a
        single company's performance against its industry peers.

        Args:
            sector: Sector name exactly as stored in the benchmark files
                    (e.g. "Technology", "Energy", "Finance").

        Returns:
            JSON object with keys:
                financial — mean financial metrics across the sector
                valuation — mean valuation/evaluation metrics across the sector
            Returns {"error": "..."} if the sector is not in the benchmark files.
        """
        try:
            financial = get_market_metrics(
                sector=sector,
                file_path=os.path.join(base_dir, "metrics_by_sectors.xlsx"),
            )
            valuation = get_market_metrics(
                sector=sector,
                file_path=os.path.join(base_dir, "eval_metrics_by_sectors.xlsx"),
            )
            result = {
                "financial": json.loads(dataframe_to_json(financial)),
                "valuation": json.loads(dataframe_to_json(valuation)),
            }
            return json.dumps(result)
        except SectorNotFoundError as exc:
            return _err(str(exc))
        except FileNotFoundError as exc:
            return _err(f"Benchmark files not found — run the pipeline first. Detail: {exc}")
        except Exception as exc:
            _logger.error("get_sector_benchmarks failed for %s", sector, exc_info=True)
            return _err(str(exc))

    @tool
    def get_red_flags(ticker: str) -> str:
        """
        Return all red-flag warnings detected for a ticker across all evaluated years.

        Red flags are early warning signals that highlight potential weaknesses in a
        company's financial statements (e.g. negative free cash flow, rising debt).

        Both qualitative flag labels (red_flags) and the raw numeric values that
        triggered them (raw_red_flags) are included in the response.

        Args:
            ticker: Ticker symbol (e.g. "AAPL", "ENI.MI").

        Returns:
            JSON object with key:
                red_flags — combined flag labels and raw numeric trigger values per year
            Returns {"error": "..."} if the ticker is not found.
        """
        try:
            # get_fin_data concatenates red_flags.xlsx + raw_red_flags.xlsx in one read
            _, _, red_flags_json = get_fin_data(ticker=ticker, base_dir=base_dir)
            return json.dumps({"red_flags": json.loads(red_flags_json)})
        except FileNotFoundError as exc:
            return _err(f"Financial data files not found — run the pipeline first. Detail: {exc}")
        except Exception as exc:
            _logger.error("get_red_flags failed for %s", ticker, exc_info=True)
            return _err(str(exc))

    @tool
    def get_stock_regime_report(ticker: str, year: int | None = None) -> str:
        """
        Run the full LLM fundamental regime assessment for a ticker.

        Calls the complete chains.py pipeline: reads Excel results, fetches sector
        benchmarks, sends data to gpt-4.1-nano, and returns a structured assessment.

        Args:
            ticker: Ticker symbol (e.g. "AAPL", "ENI.MI").
            year:   Optional year to focus the assessment on.

        Returns:
            JSON object with keys:
                regime            — "bull" or "bear"
                evaluation        — "overvalued", "undervalued", or "fair"
                regime_rationale  — LLM explanation of the bull/bear classification
                market_comparison — LLM comparison against sector peers
            Returns {"error": "..."} on any failure.
        """
        try:
            assessment = get_stock_evaluation_report(
                ticker,
                year=year,
                base_dir=base_dir,
                sector_file=sector_file,
            )
            return json.dumps(assessment.model_dump())
        except SectorNotFoundError as exc:
            return _err(f"Sector not found for {ticker}: {exc}")
        except FileNotFoundError as exc:
            return _err(f"Financial data files not found — run the pipeline first. Detail: {exc}")
        except Exception as exc:
            _logger.error("get_stock_regime_report failed for %s", ticker, exc_info=True)
            return _err(str(exc))

    return [
        list_available_tickers,
        get_stock_metrics,
        get_sector_benchmarks,
        get_red_flags,
        get_stock_regime_report,
    ]


# ---------------------------------------------------------------------------
# Convenience export — in-repo / default usage
# ---------------------------------------------------------------------------

TOOLS = make_tools()
