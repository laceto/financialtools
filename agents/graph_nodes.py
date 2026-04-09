"""
agents/graph_nodes.py — Node functions and subgraph factory for the financial analysis workflow.

Exports
-------
prepare_data_node(state)           — Stage 1: download + evaluate, writes cache
create_topic_subgraph(topic)       — Factory: returns a compiled StateGraph for one topic
compile_report_node(state)         — Stage 3: LLM synthesis → final_report

Design invariants
-----------------
- prepare_data_node calls prepare_financial_data as a plain Python function
  (not via an LLM tool call) — the LangGraph node IS the orchestrator.
- Each topic subgraph is a single-node graph: START → run_analysis → END.
  It writes exactly one state key: {topic}_result.
- compile_report_node receives all 7 topic results from state and calls the
  LLM once to produce a structured markdown report.
- All node functions return a partial AnalysisState dict (only the keys they own).
- Nodes never raise — errors surface as {"error": "..."} values in result dicts.
"""

from __future__ import annotations

import json
import logging

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from agents._tools.data_tools import prepare_financial_data
from agents._tools.topic_tools import TOPIC_TOOLS
from agents.graph_state import AnalysisState

load_dotenv()

_logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4.1-nano"

# ---------------------------------------------------------------------------
# Stage 1 — Data preparation
# ---------------------------------------------------------------------------

def prepare_data_node(state: AnalysisState) -> dict:
    """
    Download and evaluate financial data for the ticker in state.

    Calls prepare_financial_data (the LangChain tool) directly and unpacks
    the result into state keys: cache_key, company_name, resolved_sector.

    Raises ValueError if prepare_financial_data returns an error envelope.
    """
    ticker = state["ticker"]
    _logger.info("[prepare_data_node] ticker=%s sector=%s year=%s",
                 ticker, state.get("sector"), state.get("year"))

    raw = prepare_financial_data.invoke({
        "ticker": ticker,
        "sector": state.get("sector"),
        "year":   state.get("year"),
    })
    result = json.loads(raw)

    if "error" in result:
        raise ValueError(f"[prepare_data_node] {result['error']}")

    _logger.info("[prepare_data_node] cache_key=%s company=%s sector=%s",
                 result["cache_key"], result["company_name"], result["sector"])

    return {
        "cache_key":       result["cache_key"],
        "company_name":    result["company_name"],
        "resolved_sector": result["sector"],
    }


# ---------------------------------------------------------------------------
# Stage 2 — Topic subgraph factory
# ---------------------------------------------------------------------------

def create_topic_subgraph(topic: str):
    """
    Build and compile a single-node StateGraph for one topic.

    The subgraph reads cache_key from state, calls the matching topic tool,
    and writes the parsed result to state["{topic}_result"].

    Parameters
    ----------
    topic : one of the seven keys in TOPIC_TOOLS
            ("liquidity", "solvency", "profitability", "efficiency",
             "cash_flow", "growth", "red_flags")

    Returns
    -------
    Compiled LangGraph StateGraph (CompiledStateGraph).
    """
    tool_fn    = TOPIC_TOOLS[topic]
    result_key = f"{topic}_result"

    def run_analysis(state: AnalysisState) -> dict:
        cache_key = state["cache_key"]
        _logger.info("[%s] running topic '%s'", cache_key, topic)
        raw    = tool_fn.invoke({"cache_key": cache_key})
        parsed = json.loads(raw)
        # parsed may be an error dict — callers can inspect result_key for {"error": ...}
        return {result_key: parsed}

    sg = StateGraph(AnalysisState)
    sg.add_node("run_analysis", run_analysis)
    sg.add_edge(START, "run_analysis")
    sg.add_edge("run_analysis", END)
    return sg.compile()


# ---------------------------------------------------------------------------
# Stage 3 — Report compilation
# ---------------------------------------------------------------------------

_REPORT_SYSTEM = """\
You are a senior fundamental analyst at a long/short equity hedge fund.
You have received seven specialist assessments for {company_name} ({ticker}),
sector {sector}.

Your audience is a portfolio manager who needs actionable long/short conviction,
not a retail summary. Be direct, precise, and opinionated. Every claim must be
backed by a specific metric or ratio from the assessments. Do not fabricate data.
If a figure is unavailable, say so explicitly.

---

## Position Recommendation

State clearly: LONG · SHORT · NO POSITION — and the conviction level: High / Medium / Low.

Then two to three paragraphs covering:
- The primary fundamental catalyst that drives the recommended position.
- The key risk that could invalidate the thesis (stop-loss trigger).
- Suggested holding horizon: tactical (< 3 months), medium-term (3–12 months),
  or structural (> 12 months).

---

## Scorecard

Summary table with columns:
Topic | Rating / Trajectory | Signal | Long Catalyst | Short Catalyst

Where Signal is one of: ✅ Long signal · ⚠️ Neutral · 🔴 Short signal

---

## Deep-Dive by Topic

For each topic write a dedicated sub-section with:
1. **Verdict** — rating/trajectory + whether this factor supports long, short, or neither.
2. **Key metrics with values** — bullet list of every ratio or figure in the assessment.
3. **Trend** — improving / stable / deteriorating vs prior periods, with direction arrow (↑ ↓ →).
4. **Fund-level insight** — two to four sentences on what the numbers reveal about
   competitive position, capital efficiency, or earnings quality that is not
   obvious from the headline numbers.
5. **Trigger to watch** — a specific threshold, event, or data release that would
   cause the fund to add to or exit the position.

Sub-sections (use these exact headings):
### 1. Liquidity
### 2. Solvency
### 3. Profitability
### 4. Efficiency
### 5. Cash Flow
### 6. Growth
### 7. Red Flags

---

## Long Thesis

Bulleted list of three to five specific, metric-backed reasons to be long.
Each bullet must reference a concrete figure and explain the edge it represents.

---

## Short Thesis

Bulleted list of three to five specific, metric-backed reasons to be short
(or to underweight vs sector peers). Include the conditions under which
the bear case accelerates.

---

## Key Risks to the Position

For the recommended position (long or short), list the two to three scenarios
that would force a position reversal — with the specific metric levels that
would trigger reassessment.

---

## Bottom Line

One paragraph: net fundamental conviction, the single most important number
to monitor next quarter, and the event or data point that would change the call.
"""

_REPORT_HUMAN = """\
Liquidity:     {liquidity}
Solvency:      {solvency}
Profitability: {profitability}
Efficiency:    {efficiency}
Cash Flow:     {cash_flow}
Growth:        {growth}
Red Flags:     {red_flags}
"""


def compile_report_node(state: AnalysisState) -> dict:
    """
    Call the LLM once to synthesise all seven topic results into a final report.

    Writes state["final_report"] (markdown string).
    Returns {"final_report": "..."}.
    """
    ticker  = state.get("ticker", "")
    company = state.get("company_name", ticker)
    sector  = state.get("resolved_sector", "")
    model   = state.get("model", _DEFAULT_MODEL)

    def _fmt(key: str) -> str:
        val = state.get(key)
        return json.dumps(val, indent=2) if val else "unavailable"

    prompt = ChatPromptTemplate.from_messages([
        ("system", _REPORT_SYSTEM),
        ("human",  _REPORT_HUMAN),
    ])

    llm = ChatOpenAI(model=model, temperature=0)

    inputs = {
        "company_name":  company,
        "ticker":        ticker,
        "sector":        sector,
        "liquidity":     _fmt("liquidity_result"),
        "solvency":      _fmt("solvency_result"),
        "profitability": _fmt("profitability_result"),
        "efficiency":    _fmt("efficiency_result"),
        "cash_flow":     _fmt("cash_flow_result"),
        "growth":        _fmt("growth_result"),
        "red_flags":     _fmt("red_flags_result"),
    }

    _logger.info("[compile_report_node] generating final report for %s", ticker)
    response = (prompt | llm).invoke(inputs)
    report   = response.content if hasattr(response, "content") else str(response)

    _logger.info("[compile_report_node] report generated (%d chars)", len(report))
    return {"final_report": report}
