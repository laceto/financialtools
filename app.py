"""
app.py — Streamlit frontend for the financialtools topic analysis pipeline.

Run
---
    streamlit run app.py

Requires OPENAI_API_KEY in a .env file at the project root.
"""

import logging

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

from financialtools.analysis import (
    _TOPIC_MAP,
    _build_regime_chain,
    _build_topic_chain,
    _invoke_chain,
    build_weights,
    filter_year,
    normalise_time,
)
from financialtools.config import sec_sector_metric_weights
from financialtools.exceptions import EvaluationError
from financialtools.processor import Downloader, FundamentalTraderAssistant
from financialtools.utils import dataframe_to_json

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SECTOR_OPTIONS = sorted(sec_sector_metric_weights.keys())

_RATING_COLOR = {
    "strong": "green",
    "adequate": "orange",
    "weak": "red",
    "bull": "green",
    "bear": "red",
    "overvalued": "red",
    "undervalued": "green",
    "fair": "blue",
    "accelerating": "green",
    "stable": "blue",
    "decelerating": "orange",
    "declining": "red",
    "none": "green",
    "low": "blue",
    "moderate": "orange",
    "high": "red",
}

_TOPIC_LABEL = {
    "liquidity":     "Liquidity",
    "solvency":      "Solvency",
    "profitability": "Profitability",
    "efficiency":    "Efficiency",
    "cash_flow":     "Cash Flow",
    "growth":        "Growth",
    "red_flags":     "Red Flags",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _badge(label: str) -> str:
    """Return a coloured :badge[...] markdown string for a Literal label."""
    color = _RATING_COLOR.get(label, "blue")
    return f":{color}-badge[{label.upper()}]"


def _show_optional(label: str, value):
    if value:
        st.markdown(f"**{label}:** {value}")


def _topic_classification(assessment) -> str:
    """Return the primary classification field for a topic assessment."""
    if hasattr(assessment, "rating"):
        return assessment.rating
    if hasattr(assessment, "trajectory"):
        return assessment.trajectory
    if hasattr(assessment, "severity"):
        return assessment.severity
    return "—"


# ---------------------------------------------------------------------------
# Pipeline stages (exposed separately for incremental UI updates)
# ---------------------------------------------------------------------------

def _stage_download_evaluate(ticker: str, sector: str) -> dict:
    """
    Download yfinance data and run FundamentalTraderAssistant.evaluate().

    Returns the evaluate() result dict.
    Raises EvaluationError if download is empty or evaluation fails.
    """
    d = Downloader.from_ticker(ticker)
    merged = d.get_merged_data()
    if merged.empty:
        raise EvaluationError(
            f"Download returned no data for '{ticker}'. "
            "Check the ticker symbol and network connectivity."
        )
    weights = build_weights(sector)
    fta = FundamentalTraderAssistant(data=merged, weights=weights)
    return fta.evaluate()


def _build_payloads(evaluate_out: dict, year: int | None) -> dict:
    """
    Normalise time columns and serialise the five DataFrames to JSON strings.

    Returns a dict with keys: metrics, extended_metrics, composite_scores,
    eval_metrics, red_flags — ready to pass to any chain.
    """
    keys = ["metrics", "extended_metrics", "eval_metrics", "composite_scores", "red_flags"]
    payloads = {}
    for k in keys:
        df = normalise_time(evaluate_out[k])
        df = filter_year(df, year)
        payloads[k] = dataframe_to_json(df)
    return payloads


# ---------------------------------------------------------------------------
# Result display
# ---------------------------------------------------------------------------

def _render_liquidity(a):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(_badge(a.rating))
    with col2:
        st.markdown(a.rationale)
    with st.expander("Working Capital Efficiency"):
        st.markdown(a.working_capital_efficiency)
    _show_optional("Concerns", a.concerns)


def _render_solvency(a):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(_badge(a.rating))
    with col2:
        st.markdown(a.rationale)
    with st.expander("Debt Trend"):
        st.markdown(a.debt_trend)
    _show_optional("Concerns", a.concerns)


def _render_profitability(a):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(_badge(a.rating))
    with col2:
        st.markdown(a.rationale)
    with st.expander("Earnings Quality"):
        st.markdown(a.earnings_quality)
    _show_optional("Concerns", a.concerns)


def _render_efficiency(a):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(_badge(a.rating))
    with col2:
        st.markdown(a.rationale)
    with st.expander("Working Capital Chain"):
        st.markdown(a.working_capital_chain)
    _show_optional("Concerns", a.concerns)


def _render_cash_flow(a):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(_badge(a.rating))
    with col2:
        st.markdown(a.rationale)
    with st.expander("Capital Allocation"):
        st.markdown(a.capital_allocation)
    _show_optional("Concerns", a.concerns)


def _render_growth(a):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(_badge(a.trajectory))
    with col2:
        st.markdown(a.rationale)
    with st.expander("Dilution Impact"):
        st.markdown(a.dilution_impact)
    _show_optional("Concerns", a.concerns)


def _render_red_flags(a):
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(_badge(a.severity))
    with col2:
        st.markdown(a.rationale)
    if a.cash_flow_flags or a.threshold_flags or a.quality_concerns:
        with st.expander("Flag Details"):
            _show_optional("Cash Flow Flags", a.cash_flow_flags)
            _show_optional("Threshold Flags", a.threshold_flags)
            _show_optional("Quality Concerns", a.quality_concerns)


_TOPIC_RENDERERS = {
    "liquidity":     _render_liquidity,
    "solvency":      _render_solvency,
    "profitability": _render_profitability,
    "efficiency":    _render_efficiency,
    "cash_flow":     _render_cash_flow,
    "growth":        _render_growth,
    "red_flags":     _render_red_flags,
}


def _render_regime(r):
    c1, c2, c3 = st.columns(3)
    c1.metric("Regime", r.regime.upper())
    c2.metric("Valuation", r.evaluation.upper())
    c3.metric("Ticker", r.ticker)

    st.divider()
    st.markdown(f"**Regime rationale:** {r.regime_rationale}")
    st.markdown(f"**Valuation rationale:** {r.evaluation_rationale}")
    st.markdown(f"**Metrics movement:** {r.metrics_movement}")
    if r.non_aligned_findings:
        st.markdown(f"**Non-aligned findings:** {r.non_aligned_findings}")
    with st.expander("Market Comparison"):
        st.markdown(r.market_comparison)


def _render_results(results: dict):
    """Render the full result panel from session_state['results']."""
    ticker  = results["ticker"]
    regime  = results.get("regime")
    topics  = {t: results.get(t) for t in _TOPIC_MAP}

    # Summary header
    st.subheader(f"Analysis — {ticker}")
    if regime:
        cols = st.columns(len(_TOPIC_MAP) + 1)
        for i, (topic, assessment) in enumerate(topics.items()):
            label = _topic_classification(assessment) if assessment else "—"
            color = _RATING_COLOR.get(label, "blue")
            cols[i].markdown(f"**{_TOPIC_LABEL[topic]}**\n\n:{color}-badge[{label.upper()}]")
        cols[-1].markdown(f"**Regime**\n\n{_badge(regime.regime)}")

    st.divider()

    # Tabs: one per topic + overall
    tab_labels = [_TOPIC_LABEL[t] for t in _TOPIC_MAP] + ["Overall Regime"]
    tabs = st.tabs(tab_labels)

    for tab, topic in zip(tabs[:-1], _TOPIC_MAP):
        with tab:
            assessment = topics.get(topic)
            if assessment is None:
                st.warning("Chain failed for this topic — check logs.")
            else:
                _TOPIC_RENDERERS[topic](assessment)

    with tabs[-1]:
        if regime is None:
            st.warning("Regime chain failed — check logs.")
        else:
            _render_regime(regime)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Fundamental Topic Analysis",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Fundamental Topic Analysis")
st.caption(
    "Downloads yfinance fundamentals, scores 24 metrics, then runs 8 LLM chains "
    "(7 topic models + StockRegimeAssessment) for a structured fundamental assessment."
)

# --- Sidebar -----------------------------------------------------------------
with st.sidebar:
    st.header("Configuration")

    ticker = st.text_input(
        "Ticker symbol",
        value=st.session_state.get("ticker", ""),
        placeholder="e.g. AAPL, ENI.MI",
        help="Any ticker recognised by yfinance.",
    ).strip().upper()

    sector = st.selectbox(
        "Sector",
        options=SECTOR_OPTIONS,
        index=SECTOR_OPTIONS.index(st.session_state.get("sector", "Technology Services"))
        if st.session_state.get("sector", "Technology Services") in SECTOR_OPTIONS
        else 0,
    )

    year_raw = st.text_input(
        "Year filter (optional)",
        value=str(st.session_state.get("year", "")) if st.session_state.get("year") else "",
        placeholder="e.g. 2023 — leave blank for all years",
    ).strip()
    year: int | None = int(year_raw) if year_raw.isdigit() else None

    model = st.selectbox(
        "Model",
        options=["gpt-4.1-nano", "gpt-4o-mini", "gpt-4o"],
        index=0,
        help="OpenAI model used for all 8 LLM chains.",
    )

    run_btn = st.button(
        "Run Analysis",
        type="primary",
        disabled=not ticker,
        use_container_width=True,
    )

    if st.session_state.get("results"):
        if st.button("Clear Results", use_container_width=True):
            st.session_state.pop("results", None)
            st.session_state.pop("ticker", None)
            st.rerun()

# --- Run pipeline ------------------------------------------------------------
if run_btn and ticker:
    st.session_state["ticker"]  = ticker
    st.session_state["sector"]  = sector
    st.session_state["year"]    = year
    st.session_state.pop("results", None)   # clear stale results

    results: dict = {"ticker": ticker}
    total_steps = len(_TOPIC_MAP) + 2  # download+evaluate, 7 topics, 1 regime

    with st.status("Running analysis…", expanded=True) as status:

        # Stage 1: download + evaluate
        st.write(f"Downloading and evaluating **{ticker}** …")
        try:
            evaluate_out = _stage_download_evaluate(ticker, sector)
        except EvaluationError as e:
            status.update(label="Download / evaluation failed.", state="error")
            st.error(str(e))
            st.stop()

        payloads = _build_payloads(evaluate_out, year)
        results["evaluate_output"] = evaluate_out

        # Stage 2: initialise LLM once, shared across all chains
        llm = ChatOpenAI(model=model, temperature=0)

        progress = st.progress(1 / total_steps, text="Evaluation complete.")

        # Stage 3: 7 topic chains
        for i, topic in enumerate(_TOPIC_MAP, start=2):
            label = _TOPIC_LABEL[topic]
            st.write(f"Running **{label}** chain …")
            progress.progress(i / total_steps, text=f"{label} chain …")

            prompt, parser = _build_topic_chain(topic, llm)
            results[topic] = _invoke_chain(prompt, parser, llm, payloads, topic, ticker)

        # Stage 4: regime chain
        st.write("Running **Overall Regime** chain …")
        progress.progress(1.0, text="Overall Regime chain …")
        regime_prompt, regime_parser = _build_regime_chain(llm)
        results["regime"] = _invoke_chain(
            regime_prompt, regime_parser, llm, payloads, "regime", ticker
        )

        status.update(label="Analysis complete.", state="complete", expanded=False)

    st.session_state["results"] = results
    st.rerun()

# --- Show results ------------------------------------------------------------
if st.session_state.get("results"):
    _render_results(st.session_state["results"])
else:
    st.info(
        "Enter a ticker symbol and sector in the sidebar, then click **Run Analysis**.\n\n"
        "The pipeline downloads yfinance data, computes fundamental metrics, and calls "
        "8 LLM chains (one per topic + overall regime). This typically takes 30–60 seconds."
    )
