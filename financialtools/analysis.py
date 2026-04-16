"""
analysis.py — Single-ticker topic analysis pipeline.

Orchestrates download → evaluate → LLM for all seven topic models and the
overall StockRegimeAssessment in one call.

Public API
----------
run_topic_analysis(ticker, sector, year, model)  →  TopicAnalysisResult

Usage
-----
    from financialtools.analysis import run_topic_analysis

    result = run_topic_analysis("AAPL", sector="Technology", year=2023)
    print(result.regime.regime)              # "bull" | "bear"
    print(result.liquidity.rating)           # "strong" | "adequate" | "weak"
    print(result.growth.trajectory)          # "accelerating" | "stable" | ...
    print(result.evaluate_output["metrics"]) # raw DataFrame from evaluate()

Design invariants
-----------------
- Sector name must match a key in config.sec_sector_metric_weights (yfinance
  sectorKey convention, e.g. "technology", "financial-services"). Falls back
  to "Default" with a warning.
- Time column is normalised to integer years before JSON serialisation so
  the LLM receives "2022" / "2023", not "2022-12-31 00:00:00".
- All seven topic chains use the same five JSON payloads: metrics,
  extended_metrics, composite_scores, eval_metrics, red_flags.
- The overall regime chain additionally receives market_comparison as an
  empty string — it is available in StockRegimeAssessment but not fed by
  this pipeline (no benchmark files required).
- Each chain uses a one-shot output-fixing retry: if PydanticOutputParser
  fails, a follow-up LLM call asks it to correct the malformed JSON and
  tries to parse again. If the retry also fails, the topic result is None.
- run_topic_analysis() never raises on LLM failures — each topic returns
  None on error and the error is logged.

Debugging
---------
- Empty evaluate() keys → check logs/error.log for EvaluationError
- NaN extended-metric columns → optional source column absent for ticker
- LLM parse failure → _invoke_chain retries once; if it still fails
  the topic result is None and a WARNING is logged
- Sector not found → falls back to "Default" weights; logged as WARNING
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from financialtools.config import sec_sector_metric_weights
from financialtools.exceptions import EvaluationError
from financialtools.processor import Downloader, FundamentalTraderAssistant
from financialtools.pydantic_models import (
    CashFlowAssessment,
    ComprehensiveStockAssessment,
    EfficiencyAssessment,
    GrowthAssessment,
    LiquidityAssessment,
    ProfitabilityAssessment,
    QuantitativeOverviewAssessment,
    RedFlagsAssessment,
    SolvencyAssessment,
    StockRegimeAssessment,
)
from financialtools.prompts import (
    system_prompt_StockRegimeAssessment_extended,
    system_prompt_cash_flow,
    system_prompt_efficiency,
    system_prompt_growth,
    system_prompt_liquidity,
    system_prompt_profitability,
    system_prompt_quantitative_overview,
    system_prompt_red_flags,
    system_prompt_solvency,
)
from financialtools.utils import dataframe_to_json

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Topic registry — single source of truth for prompt + model pairings
# ---------------------------------------------------------------------------

_TOPIC_MAP: dict[str, tuple[str, type]] = {
    "liquidity":              (system_prompt_liquidity,             LiquidityAssessment),
    "solvency":               (system_prompt_solvency,              SolvencyAssessment),
    "profitability":          (system_prompt_profitability,         ProfitabilityAssessment),
    "efficiency":             (system_prompt_efficiency,            EfficiencyAssessment),
    "cash_flow":              (system_prompt_cash_flow,             CashFlowAssessment),
    "growth":                 (system_prompt_growth,                GrowthAssessment),
    "red_flags":              (system_prompt_red_flags,             RedFlagsAssessment),
    "quantitative_overview":  (system_prompt_quantitative_overview, QuantitativeOverviewAssessment),
}

# Human message template shared by all topic chains.
# The five JSON blocks are the same for every topic — the system prompt
# controls which fields the LLM focuses on.
_TOPIC_HUMAN_TEMPLATE = (
    "Metrics:\n{metrics}\n"
    "Extended Metrics:\n{extended_metrics}\n"
    "Scores:\n{composite_scores}\n"
    "Evaluation Metrics:\n{eval_metrics}\n"
    "RedFlags:\n{red_flags}"
)

# Human message template for the overall regime chain.
_REGIME_HUMAN_TEMPLATE = (
    "Metrics:\n{metrics}\n"
    "Extended Metrics:\n{extended_metrics}\n"
    "Scores:\n{composite_scores}\n"
    "Evaluation Metrics:\n{eval_metrics}\n"
    "RedFlags:\n{red_flags}"
)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class TopicAnalysisResult:
    """
    Structured output of run_topic_analysis().

    Every field except evaluate_output is an Optional Pydantic model.
    A None value means the LLM chain failed for that topic (error is logged).

    Fields
    ------
    ticker          : ticker symbol passed to run_topic_analysis()
    sector          : resolved sector name (may be "Default" if input not found)
    year            : optional year filter (None → all available years)
    liquidity       : LiquidityAssessment or None
    solvency        : SolvencyAssessment or None
    profitability   : ProfitabilityAssessment or None
    efficiency      : EfficiencyAssessment or None
    cash_flow       : CashFlowAssessment or None
    growth          : GrowthAssessment or None
    red_flags       : RedFlagsAssessment or None
    regime          : StockRegimeAssessment or None
    evaluate_output : raw dict from FundamentalTraderAssistant.evaluate()
                      Keys: metrics, eval_metrics, composite_scores,
                            raw_red_flags, red_flags, extended_metrics
    """

    ticker: str
    sector: str
    year: Optional[int]
    liquidity: Optional[LiquidityAssessment] = None
    solvency: Optional[SolvencyAssessment] = None
    profitability: Optional[ProfitabilityAssessment] = None
    efficiency: Optional[EfficiencyAssessment] = None
    cash_flow: Optional[CashFlowAssessment] = None
    growth: Optional[GrowthAssessment] = None
    red_flags: Optional[RedFlagsAssessment] = None
    quantitative_overview: Optional[QuantitativeOverviewAssessment] = None
    regime: Optional[StockRegimeAssessment] = None
    evaluate_output: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """
        Serialise all Pydantic assessments to plain dicts.

        Returns a dict with the same keys as the dataclass fields, where
        each Pydantic model is replaced by its .model_dump() output.
        None fields are preserved as None.
        """
        def _dump(obj):
            return obj.model_dump() if obj is not None else None

        return {
            "ticker":                self.ticker,
            "sector":                self.sector,
            "year":                  self.year,
            "liquidity":             _dump(self.liquidity),
            "solvency":              _dump(self.solvency),
            "profitability":         _dump(self.profitability),
            "efficiency":            _dump(self.efficiency),
            "cash_flow":             _dump(self.cash_flow),
            "growth":                _dump(self.growth),
            "red_flags":             _dump(self.red_flags),
            "quantitative_overview": _dump(self.quantitative_overview),
            "regime":                _dump(self.regime),
        }


# ---------------------------------------------------------------------------
# Public helpers (promoted from private in S5 fix — see code-review-report.md)
# ---------------------------------------------------------------------------

def build_weights(sector: str) -> pd.DataFrame:
    """
    Build a weights DataFrame for the given sector.

    Uses sec_sector_metric_weights (yfinance sectorKey convention, e.g. "technology").
    Falls back to 'Default' if sector is not found.

    Returns
    -------
    pd.DataFrame with columns: sector, metrics, weights.
    """
    if sector in sec_sector_metric_weights:
        sector_weights_dict = sec_sector_metric_weights[sector]
    else:
        _logger.warning(
            "Sector '%s' not found in sec_sector_metric_weights — using 'default'. "
            "Valid sectors: %s",
            sector,
            sorted(sec_sector_metric_weights.keys()),
        )
        sector_weights_dict = sec_sector_metric_weights["default"]

    # Build the weights DataFrame from the canonical sector config — single source of truth.
    return pd.DataFrame({
        "sector":  sector,
        "metrics": list(sector_weights_dict.keys()),
        "weights": list(sector_weights_dict.values()),
    })


def normalise_time(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert the 'time' column to integer years.

    Operates on a copy — does not mutate the input.

    Invariant: df must have a 'time' column parseable by pd.to_datetime.
    """
    if "time" not in df.columns or df.empty:
        return df
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"]).dt.year
    return out


def filter_year(df: pd.DataFrame, year: Optional[int]) -> pd.DataFrame:
    """Return rows matching year, or the full DataFrame if year is None."""
    if year is None or df.empty or "time" not in df.columns:
        return df
    return df[df["time"] == year].reset_index(drop=True)


_FIX_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        (
            "You are an output-fixing assistant. "
            "The JSON below failed schema validation. "
            "Rewrite it to exactly match the required schema. "
            "Output ONLY the corrected JSON — no explanation, no markdown fences.\n\n"
            "Required schema:\n{format_instructions}"
        ),
    ),
    ("human", "Malformed JSON:\n{broken}"),
])


def _build_chain_parts(system_prompt_str: str, model_cls: type, llm: ChatOpenAI):
    """
    Build prompt + parser for a topic or regime chain.

    Returns (prompt, parser) so _invoke_chain can use both for the
    primary call and the one-shot fix retry.

    Chain pattern: prompt → llm → parser
    Fix pattern  : _FIX_PROMPT → llm → parser  (on parse error)
    """
    parser = PydanticOutputParser(pydantic_object=model_cls)
    system_filled = system_prompt_str.format(
        format_instructions=parser.get_format_instructions()
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_filled),
        ("human", _TOPIC_HUMAN_TEMPLATE),
    ])
    return prompt, parser


def _build_topic_chain(topic: str, llm: ChatOpenAI):
    """
    Build prompt + parser for a topic chain.

    Returns (prompt, parser) — not a pre-built Runnable — so that
    _invoke_chain can handle the fix retry without an extra closure.

    Parameters
    ----------
    topic : one of the keys in _TOPIC_MAP
    llm   : shared ChatOpenAI instance
    """
    system_prompt_str, model_cls = _TOPIC_MAP[topic]
    return _build_chain_parts(system_prompt_str, model_cls, llm)


def _build_regime_chain(llm: ChatOpenAI):
    """
    Build prompt + parser for the overall StockRegimeAssessment chain.

    Uses system_prompt_StockRegimeAssessment_extended so the LLM sees
    all 24 scored + 14 extended unscored metrics.
    """
    parser = PydanticOutputParser(pydantic_object=StockRegimeAssessment)
    system_filled = system_prompt_StockRegimeAssessment_extended.format(
        format_instructions=parser.get_format_instructions()
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_filled),
        ("human", _REGIME_HUMAN_TEMPLATE),
    ])
    return prompt, parser


def _invoke_chain(prompt, parser, llm, inputs: dict, topic: str, ticker: str):
    """
    Invoke a chain with one-shot output-fixing retry.

    Call budget
    -----------
    - Happy path  : 1 LLM call  (primary)
    - Parse error : 2 LLM calls (primary + fix)

    Primary call: prompt | llm → parser
    On parse error: feed the *original* broken output to _FIX_PROMPT | llm,
    then parse the corrected response.
    Returns None (with a WARNING log) if the fix retry also fails.

    This replaces OutputFixingParser which was removed in LangChain 1.0.

    Invariant: the fix prompt receives the output from the *primary* call,
    not a second fresh invocation.  Re-calling the LLM before fixing would
    discard the broken output and waste a third call.
    """
    raw_chain = prompt | llm
    raw = raw_chain.invoke(inputs)          # call 1 — always made
    try:
        return parser.invoke(raw)
    except Exception as primary_exc:
        broken_content = raw.content if hasattr(raw, "content") else str(raw)
        _logger.debug(
            "[%s] '%s' primary parse failed (%s) — attempting fix retry",
            ticker, topic, primary_exc,
        )
        try:
            fix_chain = _FIX_PROMPT | llm
            fixed_raw = fix_chain.invoke({  # call 2 — fix only, no re-invoke
                "format_instructions": parser.get_format_instructions(),
                "broken": broken_content,
            })
            return parser.invoke(fixed_raw)
        except Exception as retry_exc:
            _logger.warning(
                "[%s] '%s' chain failed after fix retry: %s",
                ticker, topic, retry_exc,
            )
            return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_topic_analysis(
    ticker: str,
    sector: str,
    year: Optional[int] = None,
    model: str = "gpt-4.1-nano",
) -> TopicAnalysisResult:
    """
    Run the full fundamental analysis pipeline for a single ticker.

    Downloads yfinance data, computes 24 scored + 14 extended metrics, then
    calls eight LLM chains (seven topic models + StockRegimeAssessment) and
    returns a structured TopicAnalysisResult.

    Parameters
    ----------
    ticker  : Ticker symbol, e.g. "AAPL" or "ENI.MI".
    sector  : Sector name matching a key in config.sec_sector_metric_weights
              (yfinance sectorKey convention, e.g. "technology", "energy",
              "financial-services"). Falls back to "Default" with a warning
              if not found.
    year    : Optional year filter. When provided, only rows for that year
              are sent to the LLM. None sends all available years.
    model   : OpenAI model name (default: "gpt-4.1-nano").

    Returns
    -------
    TopicAnalysisResult
        All seven topic assessments + overall regime + raw evaluate() output.
        Individual topic fields are None if the corresponding LLM chain failed.

    Raises
    ------
    EvaluationError
        If FundamentalTraderAssistant cannot be initialised (empty download,
        bad weights, etc.). Download failures return an empty merged_df which
        also triggers EvaluationError — check logs/error.log.

    Notes
    -----
    - Requires OPENAI_API_KEY in environment or .env file.
    - LangSmith tracing is enabled automatically if LANGSMITH_API_KEY is set.
    - All LLM calls use temperature=0 for deterministic output.
    """
    # Fail fast before any network or LLM work if the key is missing.
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError(
            "OPENAI_API_KEY not set — add it to your .env file (OPENAI_API_KEY=sk-...).\n"
            "run_topic_analysis() requires an OpenAI key to call the LLM chains."
        )

    result = TopicAnalysisResult(ticker=ticker, sector=sector, year=year)

    # ------------------------------------------------------------------
    # Stage 1: Download
    # ------------------------------------------------------------------
    _logger.info("[%s] Downloading financial data …", ticker)
    d = Downloader.from_ticker(ticker)
    merged = d.get_merged_data()

    if merged.empty:
        raise EvaluationError(
            f"Download produced no data for ticker '{ticker}'. "
            "Check the ticker symbol and network connectivity."
        )

    # ------------------------------------------------------------------
    # Stage 2: Evaluate
    # ------------------------------------------------------------------
    _logger.info("[%s] Building weights for sector '%s' …", ticker, sector)
    weights = build_weights(sector)

    _logger.info("[%s] Running FundamentalTraderAssistant.evaluate() …", ticker)
    fta = FundamentalTraderAssistant(data=merged, weights=weights)
    evaluate_out = fta.evaluate()
    result.evaluate_output = evaluate_out

    # ------------------------------------------------------------------
    # Stage 3: Prepare JSON payloads
    # ------------------------------------------------------------------
    metrics_df          = evaluate_out["metrics"]
    extended_metrics_df = evaluate_out["extended_metrics"]
    eval_metrics_df     = evaluate_out["eval_metrics"]
    composite_scores_df = evaluate_out["composite_scores"]
    red_flags_df        = evaluate_out["red_flags"]

    # Normalise time → integer year, then filter if year is specified
    metrics_df          = filter_year(normalise_time(metrics_df),          year)
    extended_metrics_df = filter_year(normalise_time(extended_metrics_df), year)
    eval_metrics_df     = filter_year(normalise_time(eval_metrics_df),     year)
    composite_scores_df = filter_year(normalise_time(composite_scores_df), year)
    red_flags_df        = filter_year(normalise_time(red_flags_df),        year)

    metrics_json          = dataframe_to_json(metrics_df)
    extended_metrics_json = dataframe_to_json(extended_metrics_df)
    eval_metrics_json     = dataframe_to_json(eval_metrics_df)
    composite_scores_json = dataframe_to_json(composite_scores_df)
    red_flags_json        = dataframe_to_json(red_flags_df)

    topic_inputs = {
        "metrics":          metrics_json,
        "extended_metrics": extended_metrics_json,
        "composite_scores": composite_scores_json,
        "eval_metrics":     eval_metrics_json,
        "red_flags":        red_flags_json,
    }

    # ------------------------------------------------------------------
    # Stage 4: LLM chains
    # ------------------------------------------------------------------
    _logger.info("[%s] Initialising LLM (%s, temperature=0) …", ticker, model)
    llm = ChatOpenAI(model=model, temperature=0)

    for topic in _TOPIC_MAP:
        _logger.info("[%s] Running '%s' chain …", ticker, topic)
        prompt, parser = _build_topic_chain(topic, llm)
        assessment = _invoke_chain(prompt, parser, llm, topic_inputs, topic, ticker)
        setattr(result, topic, assessment)

    _logger.info("[%s] Running 'regime' chain …", ticker)
    regime_prompt, regime_parser = _build_regime_chain(llm)
    result.regime = _invoke_chain(
        regime_prompt, regime_parser, llm, topic_inputs, "regime", ticker
    )

    _logger.info("[%s] Analysis complete.", ticker)
    return result
