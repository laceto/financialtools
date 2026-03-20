"""
pydantic_models.py — Validated LLM output schemas for the financialtools pipeline.

Models
------
StockRegimeAssessment          (original) — overall regime + valuation classification
LiquidityAssessment            — liquidity ratios + working capital efficiency chain
SolvencyAssessment             — leverage / debt-coverage metrics + debt trend
ProfitabilityAssessment        — margin, returns, and earnings-quality metrics
EfficiencyAssessment           — asset turnover + working capital chain
CashFlowAssessment             — FCF / OCF metrics + capital-allocation narrative
GrowthAssessment               — revenue / income / FCF growth + dilution
RedFlagsAssessment             — cash-flow flags, threshold flags, and quality ratios
ComprehensiveStockAssessment   — composite wrapper containing all seven topic models

Design invariants
-----------------
- Every Literal field constrains the LLM's response vocabulary.
- Optional[str] fields default to None — the LLM may omit them when not applicable.
- Field descriptions are the only specification the LLM sees (via PydanticOutputParser
  format instructions), so they must be self-contained.
- All models are Pydantic v2. Use .model_dump() (not .dict()) for serialisation.
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# Original model — preserved for backward compatibility
# ---------------------------------------------------------------------------

class StockRegimeAssessment(BaseModel):
    ticker: str = Field(
        ..., description="The ticker of the stock under analysis"
    )
    regime: Literal["bull", "bear"] = Field(
        ..., description="The fundamental regime classification of the stock"
    )
    regime_rationale: str = Field(
        ...,
        description=(
            "Concise explanation justifying the regime classification based on "
            "the financial metrics, composite ratio and red flags"
        ),
    )
    metrics_movement: str = Field(
        ...,
        description=(
            "A summary description of how key financial metrics have moved across years, "
            "e.g., 'GrossMargin increased steadily, DebtToEquity rose sharply, FCFYield remained stable.'"
        ),
    )
    non_aligned_findings: Optional[str] = Field(
        None,
        description=(
            "Observations or signals that are not aligned with the overall metric trends, "
            "such as contradictory indicators, anomalies."
        ),
    )
    evaluation: Literal["overvalued", "undervalued", "fair"] = Field(
        ..., description="The valuation of the stock based on the Evaluation metrics"
    )
    evaluation_rationale: str = Field(
        ...,
        description=(
            "Concise explanation justifying the evaluation classification based on "
            "the financial metrics, composite ratio and red flags"
        ),
    )
    market_comparison: str = Field(
        ...,
        description=(
            "A summary description of how stock metrics compare to the market metrics "
            "in term of fundamentals and valuation"
        ),
    )


# ---------------------------------------------------------------------------
# Topic models — one per metric group
# ---------------------------------------------------------------------------

class LiquidityAssessment(BaseModel):
    """
    Structured LLM output for the liquidity metric group.

    Scored inputs  : CurrentRatio, QuickRatio, CashRatio, WorkingCapitalRatio
    Extended inputs: DSO, DIO, DPO, CCC (working capital efficiency chain)
    """

    rating: Literal["strong", "adequate", "weak"] = Field(
        ...,
        description=(
            "Overall liquidity rating. "
            "'strong' = company can comfortably meet short-term obligations; "
            "'adequate' = liquidity is sufficient but may tighten under stress; "
            "'weak' = material risk of meeting near-term obligations."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Concise justification for the rating drawing on CurrentRatio, QuickRatio, "
            "CashRatio, and WorkingCapitalRatio across all available years. "
            "Note any trend (improving, stable, deteriorating)."
        ),
    )
    working_capital_efficiency: str = Field(
        ...,
        description=(
            "Narrative on the working capital efficiency chain: "
            "DSO (days to collect receivables), DIO (days inventory is held), "
            "DPO (days payables are outstanding), and CCC (Cash Conversion Cycle = DSO + DIO - DPO). "
            "Lower CCC is generally better. Highlight if CCC is lengthening or shortening over time."
        ),
    )
    concerns: Optional[str] = Field(
        None,
        description=(
            "Specific liquidity concerns or anomalies not captured by the rating, "
            "e.g. a high CurrentRatio driven by illiquid inventory, or a very short DPO "
            "suggesting strained supplier relationships. None if no concerns."
        ),
    )


class SolvencyAssessment(BaseModel):
    """
    Structured LLM output for the solvency / leverage metric group.

    Scored inputs  : DebtToEquity, DebtRatio, EquityRatio, NetDebtToEBITDA, InterestCoverage
    Extended inputs: DebtGrowth (year-over-year change in total debt)
    """

    rating: Literal["strong", "adequate", "weak"] = Field(
        ...,
        description=(
            "Overall solvency rating. "
            "'strong' = low leverage, comfortable coverage; "
            "'adequate' = leverage is manageable but warrants monitoring; "
            "'weak' = high leverage or insufficient interest coverage poses risk."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Concise justification drawing on DebtToEquity, DebtRatio, EquityRatio, "
            "NetDebtToEBITDA, and InterestCoverage. Note sector context where relevant "
            "(e.g. higher leverage is common in utilities and financials)."
        ),
    )
    debt_trend: str = Field(
        ...,
        description=(
            "Narrative on DebtGrowth (year-over-year percent change in total debt). "
            "Characterise whether the company is actively deleveraging, holding debt stable, "
            "or accumulating debt rapidly, and what this implies for future solvency."
        ),
    )
    concerns: Optional[str] = Field(
        None,
        description=(
            "Specific solvency concerns not captured above, e.g. debt maturing in the near term, "
            "covenant risk, or NetDebtToEBITDA exceeding sector norms. None if no concerns."
        ),
    )


class ProfitabilityAssessment(BaseModel):
    """
    Structured LLM output for the profitability metric group.

    Scored inputs  : GrossMargin, OperatingMargin, NetProfitMargin, EBITDAMargin, ROA, ROE, ROIC
    Extended inputs: Accruals ((net_income - OCF) / total_assets — earnings quality signal)
    """

    rating: Literal["strong", "adequate", "weak"] = Field(
        ...,
        description=(
            "Overall profitability rating. "
            "'strong' = healthy and improving margins with solid returns on capital; "
            "'adequate' = margins and returns are positive but modest or under pressure; "
            "'weak' = thin or negative margins, poor capital returns."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Concise justification drawing on GrossMargin, OperatingMargin, NetProfitMargin, "
            "EBITDAMargin, ROA, ROE, and ROIC. Highlight multi-year trends "
            "(expanding vs. compressing margins, improving vs. declining returns on capital)."
        ),
    )
    earnings_quality: str = Field(
        ...,
        description=(
            "Assessment of earnings quality using the Accruals ratio "
            "((net_income - operating_cash_flow) / total_assets). "
            "High positive Accruals suggest reported earnings are not well-supported by cash flow "
            "and may be inflated. Low or negative Accruals indicate high cash-backed earnings quality."
        ),
    )
    concerns: Optional[str] = Field(
        None,
        description=(
            "Specific profitability concerns, e.g. margin compression driven by rising input costs, "
            "ROIC declining below cost of capital, or large accruals divergence. None if no concerns."
        ),
    )


class EfficiencyAssessment(BaseModel):
    """
    Structured LLM output for the operational efficiency metric group.

    Scored inputs  : AssetTurnover
    Extended inputs: ReceivablesTurnover, DSO, InventoryTurnover, DIO,
                     PayablesTurnover, DPO, CCC
    """

    rating: Literal["strong", "adequate", "weak"] = Field(
        ...,
        description=(
            "Overall operational efficiency rating. "
            "'strong' = high asset utilisation and short cash conversion cycle; "
            "'adequate' = efficiency is acceptable but with room for improvement; "
            "'weak' = low asset turnover or lengthening CCC signals operational drag."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Concise justification drawing on AssetTurnover. "
            "Note whether the company generates more revenue per unit of assets over time "
            "and how this compares to sector norms."
        ),
    )
    working_capital_chain: str = Field(
        ...,
        description=(
            "Detailed narrative on the working capital efficiency chain: "
            "ReceivablesTurnover and DSO (speed of collecting receivables — lower DSO is better), "
            "InventoryTurnover and DIO (speed of selling inventory — lower DIO is better), "
            "PayablesTurnover and DPO (how long the company takes to pay suppliers — higher DPO is better), "
            "and the resulting CCC (DSO + DIO - DPO — lower is better). "
            "Comment on multi-year trends and any notable changes."
        ),
    )
    concerns: Optional[str] = Field(
        None,
        description=(
            "Specific efficiency concerns, e.g. a sharply lengthening CCC, "
            "rising DSO suggesting collection problems, or DPO declining sharply. None if no concerns."
        ),
    )


class CashFlowAssessment(BaseModel):
    """
    Structured LLM output for the cash flow metric group.

    Scored inputs  : FCFToRevenue, FCFYield, FCFtoDebt, OCFRatio, FCFMargin,
                     CashConversion, CapexRatio
    Extended inputs: FCFGrowth, CapexToDepreciation
    """

    rating: Literal["strong", "adequate", "weak"] = Field(
        ...,
        description=(
            "Overall cash flow rating. "
            "'strong' = consistently positive and growing FCF with good cash conversion; "
            "'adequate' = positive FCF but with variability or modest conversion; "
            "'weak' = negative or declining FCF, poor cash conversion, or heavy capex burden."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Concise justification drawing on FCFToRevenue, FCFYield, FCFtoDebt, OCFRatio, "
            "FCFMargin, CashConversion, and CapexRatio. "
            "Highlight whether the company is generating cash efficiently from operations "
            "and whether capex consumes a growing share of operating cash flow."
        ),
    )
    capital_allocation: str = Field(
        ...,
        description=(
            "Narrative on capital allocation intensity using FCFGrowth "
            "(year-over-year FCF growth) and CapexToDepreciation "
            "(capital expenditure / depreciation — values well above 1.0 indicate heavy reinvestment). "
            "Assess whether capex is growing assets productively or merely maintaining them."
        ),
    )
    concerns: Optional[str] = Field(
        None,
        description=(
            "Specific cash flow concerns, e.g. FCF turning negative, "
            "CashConversion falling sharply below 1.0 (earnings not converting to cash), "
            "or CapexRatio rising above 0.6 leaving little free cash. None if no concerns."
        ),
    )


class GrowthAssessment(BaseModel):
    """
    Structured LLM output for the growth metric group.

    Extended inputs: RevenueGrowth, NetIncomeGrowth, FCFGrowth (year-over-year pct change),
                     Dilution (year-over-year change in shares outstanding)
    """

    trajectory: Literal["accelerating", "stable", "decelerating", "declining"] = Field(
        ...,
        description=(
            "Overall growth trajectory. "
            "'accelerating' = growth rates are increasing year-over-year; "
            "'stable' = consistent positive growth; "
            "'decelerating' = growth is positive but slowing; "
            "'declining' = revenue, income, or FCF is contracting."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Concise justification drawing on RevenueGrowth, NetIncomeGrowth, and FCFGrowth "
            "across all available years. Note whether income and FCF are growing faster or slower "
            "than revenue (operating leverage signal)."
        ),
    )
    dilution_impact: str = Field(
        ...,
        description=(
            "Assessment of share dilution using the Dilution metric "
            "(year-over-year growth rate in shares outstanding). "
            "Positive values reduce per-share value even if absolute earnings grow. "
            "Note whether buybacks (negative Dilution) are offsetting or compounding the effect."
        ),
    )
    concerns: Optional[str] = Field(
        None,
        description=(
            "Specific growth concerns, e.g. revenue growing but FCFGrowth declining "
            "(margin erosion), or persistent dilution offsetting earnings growth. None if no concerns."
        ),
    )


class RedFlagsAssessment(BaseModel):
    """
    Structured LLM output for the red flags metric group.

    Scored inputs (raw_red_flags) : negative FCF, negative OCF, EBITDA >> OCF
    Scored inputs (red_flags)     : negative margins, high D/E, negative ROA/ROE
    Extended inputs               : Accruals, DebtGrowth, Dilution, CapexToDepreciation
    """

    severity: Literal["none", "low", "moderate", "high"] = Field(
        ...,
        description=(
            "Overall red flag severity. "
            "'none' = no warnings detected; "
            "'low' = minor anomalies, not immediately concerning; "
            "'moderate' = multiple flags that warrant close monitoring; "
            "'high' = serious warnings indicating material risk."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Concise summary of the combined red flag picture, drawing on all detected flags "
            "from cash-flow quality checks, threshold-based flags, and extended quality ratios. "
            "Explain whether the flags cluster around a single risk area or span multiple dimensions."
        ),
    )
    cash_flow_flags: Optional[str] = Field(
        None,
        description=(
            "Cash-flow quality flags detected (raw_red_flags): "
            "negative free cash flow, negative operating cash flow, or EBITDA materially exceeding OCF. "
            "None if no cash-flow flags were triggered."
        ),
    )
    threshold_flags: Optional[str] = Field(
        None,
        description=(
            "Threshold-based flags detected (red_flags): "
            "negative gross/operating/net margins, negative ROA or ROE, high DebtToEquity. "
            "None if no threshold flags were triggered."
        ),
    )
    quality_concerns: Optional[str] = Field(
        None,
        description=(
            "Earnings and capital quality concerns from extended metrics: "
            "high Accruals (earnings not cash-backed), rapid DebtGrowth, "
            "persistent Dilution, or CapexToDepreciation well above 1.0. "
            "None if no quality concerns are present."
        ),
    )


# ---------------------------------------------------------------------------
# Composite model — contains all seven topic assessments
# ---------------------------------------------------------------------------

class ComprehensiveStockAssessment(BaseModel):
    """
    Composite LLM output wrapping all seven topic-focused assessments plus
    an overall regime classification.

    Use this model when the full extended_metrics payload is available and
    you want the LLM to produce a structured report across all metric groups
    in a single call.

    Invariant: all seven sub-models must be present — the LLM may not omit them.
    If a topic cannot be assessed due to missing data, the sub-model's rationale
    field should state that explicitly and the rating/severity should be set to
    the neutral value ('adequate' or 'none').
    """

    ticker: str = Field(
        ..., description="The ticker symbol of the stock under analysis"
    )
    regime: Literal["bull", "bear"] = Field(
        ...,
        description=(
            "Overall fundamental regime: 'bull' = strong/improving fundamentals; "
            "'bear' = weak/deteriorating fundamentals."
        ),
    )
    regime_rationale: str = Field(
        ...,
        description=(
            "Top-level summary justifying the overall regime, synthesising findings "
            "across all seven topic assessments and the composite score."
        ),
    )
    evaluation: Literal["overvalued", "undervalued", "fair"] = Field(
        ...,
        description=(
            "Valuation classification based on evaluation metrics "
            "(P/E, P/B, P/FCF, EarningsYield, FCFYield) and sector comparison."
        ),
    )
    liquidity: LiquidityAssessment = Field(
        ..., description="Detailed assessment of liquidity ratios and working capital efficiency."
    )
    solvency: SolvencyAssessment = Field(
        ..., description="Detailed assessment of leverage, debt coverage, and debt trend."
    )
    profitability: ProfitabilityAssessment = Field(
        ..., description="Detailed assessment of margin, returns, and earnings quality."
    )
    efficiency: EfficiencyAssessment = Field(
        ..., description="Detailed assessment of asset utilisation and working capital chain."
    )
    cash_flow: CashFlowAssessment = Field(
        ..., description="Detailed assessment of free cash flow generation and capital allocation."
    )
    growth: GrowthAssessment = Field(
        ..., description="Detailed assessment of revenue, income, and FCF growth trajectories."
    )
    red_flags: RedFlagsAssessment = Field(
        ..., description="Consolidated assessment of all cash-flow, threshold, and quality red flags."
    )
