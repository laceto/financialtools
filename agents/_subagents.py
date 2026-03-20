"""
agents/_subagents.py — Topic subagent definitions for the financial analysis manager.

Each entry in TOPIC_SUBAGENTS is a dict accepted by create_deep_agent(subagents=[...]).
The manager delegates to them via the built-in `task` tool.

Subagent inventory
------------------
liquidity_analyst     — CurrentRatio, QuickRatio, CashRatio, WC chain
solvency_analyst      — DebtToEquity, NetDebtToEBITDA, InterestCoverage, DebtGrowth
profitability_analyst — Margins, ROA, ROE, ROIC, Accruals
efficiency_analyst    — AssetTurnover, ReceivablesTurnover, DIO, DPO, CCC
cash_flow_analyst     — FCF metrics, OCFRatio, CashConversion, CapexRatio
growth_analyst        — RevenueGrowth, NetIncomeGrowth, FCFGrowth, Dilution
red_flags_analyst     — Raw flags, threshold flags, quality ratios

Design invariants
-----------------
- Each subagent has exactly one analysis tool matching its specialty.
- System prompts are concise: role statement + tool usage instruction.
- Subagents are stateless — instructions must be complete in one call.
  The manager must include the cache_key in every delegation instruction.
"""

from __future__ import annotations

from agents._tools.topic_tools import TOPIC_TOOLS

# ─── Per-topic metadata ───────────────────────────────────────────────────────
# (name, description, tool_name, system_prompt)

_SUBAGENT_META: list[tuple[str, str, str, str]] = [
    (
        "liquidity_analyst",
        (
            "Specialist in short-term liquidity analysis: CurrentRatio, QuickRatio, "
            "CashRatio, WorkingCapitalRatio, and the DSO/DIO/DPO/CCC efficiency chain."
        ),
        "liquidity",
        (
            "You are a liquidity analyst specialising in a company's ability to meet "
            "short-term obligations.  You have access to the run_liquidity_analysis tool.\n\n"
            "When given a cache_key, call run_liquidity_analysis(cache_key=<key>) and "
            "return the full JSON result with no additional commentary."
        ),
    ),
    (
        "solvency_analyst",
        (
            "Specialist in leverage and long-term solvency: DebtToEquity, DebtRatio, "
            "EquityRatio, NetDebtToEBITDA, InterestCoverage, and DebtGrowth trend."
        ),
        "solvency",
        (
            "You are a solvency analyst specialising in leverage, debt coverage, and "
            "long-term financial stability.  You have access to the run_solvency_analysis tool.\n\n"
            "When given a cache_key, call run_solvency_analysis(cache_key=<key>) and "
            "return the full JSON result with no additional commentary."
        ),
    ),
    (
        "profitability_analyst",
        (
            "Specialist in profitability: GrossMargin, OperatingMargin, NetProfitMargin, "
            "EBITDAMargin, ROA, ROE, ROIC, and earnings quality via Accruals ratio."
        ),
        "profitability",
        (
            "You are a profitability analyst specialising in margin analysis, capital returns, "
            "and earnings quality.  You have access to the run_profitability_analysis tool.\n\n"
            "When given a cache_key, call run_profitability_analysis(cache_key=<key>) and "
            "return the full JSON result with no additional commentary."
        ),
    ),
    (
        "efficiency_analyst",
        (
            "Specialist in operational efficiency: AssetTurnover, ReceivablesTurnover, "
            "InventoryTurnover, PayablesTurnover, and the DSO/DIO/DPO/CCC chain."
        ),
        "efficiency",
        (
            "You are an efficiency analyst specialising in asset utilisation and working capital "
            "management.  You have access to the run_efficiency_analysis tool.\n\n"
            "When given a cache_key, call run_efficiency_analysis(cache_key=<key>) and "
            "return the full JSON result with no additional commentary."
        ),
    ),
    (
        "cash_flow_analyst",
        (
            "Specialist in cash flow quality: FCFToRevenue, FCFYield, FCFtoDebt, OCFRatio, "
            "FCFMargin, CashConversion, CapexRatio, FCFGrowth, and CapexToDepreciation."
        ),
        "cash_flow",
        (
            "You are a cash flow analyst specialising in free cash flow generation, "
            "operating cash conversion, and capital allocation intensity.  "
            "You have access to the run_cash_flow_analysis tool.\n\n"
            "When given a cache_key, call run_cash_flow_analysis(cache_key=<key>) and "
            "return the full JSON result with no additional commentary."
        ),
    ),
    (
        "growth_analyst",
        (
            "Specialist in growth trajectories: RevenueGrowth, NetIncomeGrowth, FCFGrowth "
            "(year-over-year), and shareholder dilution trends."
        ),
        "growth",
        (
            "You are a growth analyst specialising in revenue, earnings, and cash flow growth "
            "trajectories and shareholder dilution.  "
            "You have access to the run_growth_analysis tool.\n\n"
            "When given a cache_key, call run_growth_analysis(cache_key=<key>) and "
            "return the full JSON result with no additional commentary."
        ),
    ),
    (
        "red_flags_analyst",
        (
            "Specialist in detecting financial red flags: negative FCF/OCF, margin failures, "
            "excessive leverage, high Accruals, rapid DebtGrowth, and Dilution signals."
        ),
        "red_flags",
        (
            "You are a red flags analyst specialising in detecting early warning signs of "
            "financial distress or earnings manipulation.  "
            "You have access to the run_red_flags_analysis tool.\n\n"
            "When given a cache_key, call run_red_flags_analysis(cache_key=<key>) and "
            "return the full JSON result with no additional commentary."
        ),
    ),
]


def build_topic_subagents(model: str = "gpt-4.1-nano") -> list[dict]:
    """
    Build the list of subagent dicts accepted by create_deep_agent(subagents=...).

    Args:
        model: LLM model name for all subagents (default: "gpt-4.1-nano").

    Returns:
        List of seven dicts, one per topic.
    """
    subagents = []
    for name, description, topic_key, system_prompt in _SUBAGENT_META:
        subagents.append({
            "name":          name,
            "description":   description,
            "system_prompt": system_prompt,
            "model":         model,
            "tools":         [TOPIC_TOOLS[topic_key]],
        })
    return subagents


# Pre-built default list (uses gpt-4.1-nano)
TOPIC_SUBAGENTS = build_topic_subagents()
