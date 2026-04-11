"""
prompts.py — LLM system prompts for financialtools output models.

Design:
  Shared metric-definition blocks are defined once as module-level constants and
  composed by two prompt factories:

  build_prompt(sector_aware, include_red_flags, include_extended_metrics)
      Builds prompts for StockRegimeAssessment (overall regime + valuation).

  build_topic_prompt(topic)
      Builds prompts for the seven topic-focused models (LiquidityAssessment, …,
      RedFlagsAssessment) and the ComprehensiveStockAssessment wrapper.
      topic must be one of: 'liquidity', 'solvency', 'profitability', 'efficiency',
      'cash_flow', 'growth', 'red_flags', 'comprehensive'.

  Adding or changing a metric definition requires editing only one block constant.

Regime / valuation prompts (StockRegimeAssessment):
  system_prompt_StockRegimeAssessment         — base: 24 scored metrics + red flags
  system_prompt_StockRegimeAssessment_sector  — base + sector comparison instruction
  system_prompt_noredflags_StockRegimeAssessment — base without red flags section
  system_prompt_StockRegimeAssessment_extended   — base + 14 unscored extended metrics
  system_prompt                               — rich: profile + peer benchmarks + sector

Topic-focused prompts (one per pydantic_models topic model):
  system_prompt_liquidity       — LiquidityAssessment
  system_prompt_solvency        — SolvencyAssessment
  system_prompt_profitability   — ProfitabilityAssessment
  system_prompt_efficiency      — EfficiencyAssessment
  system_prompt_cash_flow       — CashFlowAssessment
  system_prompt_growth          — GrowthAssessment
  system_prompt_red_flags       — RedFlagsAssessment
  system_prompt_comprehensive   — ComprehensiveStockAssessment
"""

# ---------------------------------------------------------------------------
# Shared blocks — single source of truth for metric definitions
# ---------------------------------------------------------------------------

_FINANCIAL_METRICS_BLOCK = """Financial metrics provided are the following:

Profitability and Margin Metrics:
    -GrossMargin: gross profit / total revenue
    -OperatingMargin: operating income / total revenue
    -NetProfitMargin: net income / total revenue
    -EBITDAMargin: ebitda / total revenue
Returns metrics:
    -ROA: net income / total assets
    -ROE: net income / total equity
    -ROIC: ebit * (1 - tax_rate) / invested_capital
Cash Flow Strength metrics:
    -FCFToRevenue: free cash flow / total revenue
    -FCFYield: free cash flow / market capitalization
    -FCFtoDebt: free cash flow / total debt
    -OCFRatio: operating cash flow / current liabilities
    -FCFMargin: free cash flow / total revenue
    -CashConversion: operating cash flow / net income
    -CapexRatio: capital expenditure / operating cash flow (lower is better)
Leverage & Solvency metrics:
    -DebtToEquity: total debt / total equity (lower is better)
    -DebtRatio: total debt / total assets (lower is better)
    -EquityRatio: total equity / total assets
    -NetDebtToEBITDA: net debt / ebitda (lower is better)
    -InterestCoverage: ebit / interest expense
Liquidity metrics:
    -CurrentRatio: current assets / current liabilities
    -QuickRatio: (current assets - inventory) / current liabilities
    -CashRatio: cash and equivalents / current liabilities
    -WorkingCapitalRatio: working capital / current assets
Efficiency metrics:
    -AssetTurnover: total revenue / total assets"""

_EXTENDED_METRICS_BLOCK = """Extended metrics are unscored diagnostic indicators. They are NOT factored \
into the composite score but provide additional context on operational efficiency, growth \
trajectory, and early-warning signals.

Working Capital Efficiency Chain:
    -ReceivablesTurnover: total revenue / accounts receivable
    -DSO (Days Sales Outstanding): 365 / ReceivablesTurnover — lower is better
    -InventoryTurnover: cost of revenue / inventory
    -DIO (Days Inventory Outstanding): 365 / InventoryTurnover — lower is better
    -PayablesTurnover: cost of revenue / accounts payable
    -DPO (Days Payable Outstanding): 365 / PayablesTurnover — higher is better
    -CCC (Cash Conversion Cycle): DSO + DIO - DPO — lower is better
Growth Rates (year-over-year percent change):
    -RevenueGrowth: (revenue_t / revenue_t-1) - 1
    -NetIncomeGrowth: (net_income_t / net_income_t-1) - 1
    -FCFGrowth: (fcf_t / fcf_t-1) - 1
Red-Flag Ratios:
    -Accruals: (net_income - operating_cash_flow) / total_assets — high positive values signal earnings quality risk
    -DebtGrowth: year-over-year growth in total debt — rapid growth signals rising leverage risk
    -Dilution: year-over-year growth in shares outstanding — positive values reduce per-share value
    -CapexToDepreciation: capital_expenditure / depreciation — values well above 1.0 signal heavy reinvestment"""

_EVAL_METRICS_BLOCK = """Evaluation metrics provided are the following:
    -bvps: total equity / shares outstanding
    -fcf_per_share: free cash flow / shares outstanding
    -eps: earning per share
    -P/E: current stock price / eps
    -P/B: current stock price / bvps
    -P/FCF: current stock price / fcf_per_share
    -EarningsYield: eps / current stock price
    -FCFYield: free cash flow / market capitalization"""

_COMPOSITE_SCORE_BLOCK = """The composite score is a weighted average (1 to 5) that summarizes the company's overall fundamental health.
It reflects profitability, efficiency, leverage, liquidity, and cash flow strength, based on the above mentioned financial metrics (evaluation metrics and extended metrics do not factor into the calculation).

The composite score ranges:
1 = Weak fundamentals
5 = Strong fundamentals

Each financial metric is scored on a 1–5 scale and multiplied by its weight. The composite score is the sum of weighted scores divided by the total weight.
Four metrics use inverse scoring (lower value = higher score): DebtToEquity, DebtRatio, NetDebtToEBITDA, CapexRatio."""

_RED_FLAGS_BLOCK = """A red flag is an early warning signal that highlights potential weaknesses in a company's financial statements \
or business quality. These warnings do not always mean immediate distress, but they indicate heightened risk that \
traders should carefully consider before taking a position."""

# ---------------------------------------------------------------------------
# Prompt factory
# ---------------------------------------------------------------------------

def build_prompt(
    sector_aware: bool = False,
    include_red_flags: bool = True,
    include_extended_metrics: bool = False,
) -> str:
    """
    Compose a StockRegimeAssessment system prompt from shared building blocks.

    Args:
        sector_aware: If True, appends the sector-comparison instruction.
        include_red_flags: If True, mentions red flags in the data description
                           and includes the red flags definition block.
        include_extended_metrics: If True, appends the extended metrics block
                                  (working capital chain, growth rates, red-flag
                                  ratios). Use when extended_metrics is present
                                  in the evaluate() result passed to the LLM.

    Returns:
        A formatted system prompt string.
    """
    parts = ["financial metrics", "evaluation metrics", "composite score"]
    if include_red_flags:
        parts.append("red flags")
    if include_extended_metrics:
        parts.append("extended metrics")
    data_description = "Financial data consists of " + ", ".join(parts) + "."

    red_flags_section = f"\n\n{_RED_FLAGS_BLOCK}\n" if include_red_flags else "\n"
    extended_section = f"\n\n{_EXTENDED_METRICS_BLOCK}\n" if include_extended_metrics else ""

    sector_section = (
        "\nMake sure to assess the stock based on the sector it operates on and compare it to the market data provided. \n"
        if sector_aware
        else ""
    )

    return (
        "You are a trader assistant specializing in fundamental analysis. \n\n"
        "Based on the following financial data, provide a concise overall assessment that classifies \n"
        "the stock's current fundamental regime as one of:\n\n"
        "- bull: Strong and improving fundamentals supporting a positive outlook.\n"
        "- bear: Weak or deteriorating fundamentals indicating risk or decline.\n\n"
        f"{data_description}\n\n"
        f"{_FINANCIAL_METRICS_BLOCK}\n\n\n"
        f"{_EVAL_METRICS_BLOCK}\n\n"
        f"{_COMPOSITE_SCORE_BLOCK}\n"
        f"{red_flags_section}"
        f"{extended_section}"
        f"{sector_section}"
    )


# ---------------------------------------------------------------------------
# Public prompt constants — backward-compatible module-level names
# imported by chains.py and any other caller.
# ---------------------------------------------------------------------------

system_prompt_StockRegimeAssessment = build_prompt(
    sector_aware=False,
    include_red_flags=True,
)

system_prompt_StockRegimeAssessment_sector = build_prompt(
    sector_aware=True,
    include_red_flags=True,
)

system_prompt_noredflags_StockRegimeAssessment = build_prompt(
    sector_aware=False,
    include_red_flags=False,
)

system_prompt_StockRegimeAssessment_extended = build_prompt(
    sector_aware=True,
    include_red_flags=True,
    include_extended_metrics=True,
)

# system_prompt is structurally different (profile section, peer benchmarks, emoji headers).
# It is kept as a literal string because its structure diverges too much from the
# build_prompt() factory to benefit from composition without adding brittle conditionals.
# _FINANCIAL_METRICS_BLOCK, _EVAL_METRICS_BLOCK, and _EXTENDED_METRICS_BLOCK are
# referenced inline to keep metric definitions in sync with the shared blocks.
system_prompt = (
    "You are a trader assistant specializing in fundamental analysis.\n\n"
    "Your task is to assess the fundamental health of a stock based on the provided \n"
    "    financial data, \n"
    "    stock profile information, and \n"
    "    peer benchmarks. \n\n"
    "Classify the stock's current regime as one of:\n"
    "- bull: Strong and improving fundamentals supporting a positive outlook.\n"
    "- bear: Weak or deteriorating fundamentals indicating risk or decline.\n\n"
    "The input includes:\n"
    "- Stock profile information\n"
    "- Financial metrics (24 scored)\n"
    "- Evaluation metrics\n"
    "- Composite score\n"
    "- Red flags\n"
    "- Extended metrics (14 unscored diagnostics)\n"
    "- Peer average metrics\n\n"
    "📌 Stock Profile Information:\n"
    "Includes the company name, a brief description of its business operations, and the industry and sector it belongs to. \n"
    "Use this context to tailor your assessment to the company's specific business model and competitive environment.\n\n"
    "📊 Financial Metrics:\n"
    "These 24 scored metrics reflect the company's operational and financial performance "
    "and determine the composite score.\n\n"
    "Profitability and Margin:\n"
    "    -GrossMargin: gross profit / total revenue\n"
    "    -OperatingMargin: operating income / total revenue\n"
    "    -NetProfitMargin: net income / total revenue\n"
    "    -EBITDAMargin: ebitda / total revenue\n\n"
    "Returns:\n"
    "    -ROA: net income / total assets\n"
    "    -ROE: net income / total equity\n"
    "    -ROIC: ebit * (1 - tax_rate) / invested_capital\n\n"
    "Cash Flow Strength:\n"
    "    -FCFToRevenue: free cash flow / total revenue\n"
    "    -FCFYield: free cash flow / market capitalization\n"
    "    -FCFtoDebt: free cash flow / total debt\n"
    "    -OCFRatio: operating cash flow / current liabilities\n"
    "    -FCFMargin: free cash flow / total revenue\n"
    "    -CashConversion: operating cash flow / net income\n"
    "    -CapexRatio: capital expenditure / operating cash flow (lower is better)\n\n"
    "Leverage & Solvency:\n"
    "    -DebtToEquity: total debt / total equity (lower is better)\n"
    "    -DebtRatio: total debt / total assets (lower is better)\n"
    "    -EquityRatio: total equity / total assets\n"
    "    -NetDebtToEBITDA: net debt / ebitda (lower is better)\n"
    "    -InterestCoverage: ebit / interest expense\n\n"
    "Liquidity:\n"
    "    -CurrentRatio: current assets / current liabilities\n"
    "    -QuickRatio: (current assets - inventory) / current liabilities\n"
    "    -CashRatio: cash and equivalents / current liabilities\n"
    "    -WorkingCapitalRatio: working capital / current assets\n\n"
    "Efficiency:\n"
    "    -AssetTurnover: total revenue / total assets\n\n"
    "📈 Evaluation Metrics:\n"
    "These reflect market valuation and shareholder returns. "
    "They do not influence the composite score.\n\n"
    "    -bvps: total equity / shares outstanding\n"
    "    -fcf_per_share: free cash flow / shares outstanding\n"
    "    -eps: earning per share\n"
    "    -P/E: current stock price / eps\n"
    "    -P/B: current stock price / bvps\n"
    "    -P/FCF: current stock price / fcf_per_share\n"
    "    -EarningsYield: eps / current stock price\n"
    "    -FCFYield: free cash flow / market capitalization\n\n"
    "🧮 Composite Score:\n"
    "A weighted average (1 to 5) summarizing the company's fundamental health. \n"
    "It incorporates all 24 financial metrics above. "
    "Evaluation metrics and extended metrics do not influence this score.\n"
    "Four metrics use inverse scoring (lower value = higher score): "
    "DebtToEquity, DebtRatio, NetDebtToEBITDA, CapexRatio.\n\n"
    "    - 1 = Weak fundamentals\n"
    "    - 5 = Strong fundamentals\n\n"
    "Each financial metric is scored on a 1–5 scale and multiplied by its assigned weight. \n"
    "The composite score is the sum of weighted scores divided by the total weight.\n\n"
    "🚨 Red Flags:\n"
    "Indicators of potential weaknesses in financial statements or business quality. \n"
    "These do not imply immediate distress but signal elevated risk that traders should factor into their decisions.\n\n"
    "📐 Extended Metrics:\n"
    "Unscored diagnostic indicators. NOT factored into the composite score. "
    "Use them to enrich your assessment with operational context.\n\n"
    "Working Capital Efficiency Chain:\n"
    "    -ReceivablesTurnover: total revenue / accounts receivable\n"
    "    -DSO (Days Sales Outstanding): 365 / ReceivablesTurnover — lower is better\n"
    "    -InventoryTurnover: cost of revenue / inventory\n"
    "    -DIO (Days Inventory Outstanding): 365 / InventoryTurnover — lower is better\n"
    "    -PayablesTurnover: cost of revenue / accounts payable\n"
    "    -DPO (Days Payable Outstanding): 365 / PayablesTurnover — higher is better\n"
    "    -CCC (Cash Conversion Cycle): DSO + DIO - DPO — lower is better\n\n"
    "Growth Rates (year-over-year):\n"
    "    -RevenueGrowth: (revenue_t / revenue_t-1) - 1\n"
    "    -NetIncomeGrowth: (net_income_t / net_income_t-1) - 1\n"
    "    -FCFGrowth: (fcf_t / fcf_t-1) - 1\n\n"
    "Red-Flag Ratios:\n"
    "    -Accruals: (net_income - operating_cash_flow) / total_assets — high positive values signal earnings quality risk\n"
    "    -DebtGrowth: year-over-year growth in total debt — rapid growth signals rising leverage risk\n"
    "    -Dilution: year-over-year growth in shares outstanding — positive values reduce per-share value\n"
    "    -CapexToDepreciation: capital_expenditure / depreciation — values well above 1.0 signal heavy reinvestment\n\n"
    "📊 Peer Average Metrics:\n"
    "You will also be provided with peer average values for both financial and evaluation metrics. \n"
    "Use these benchmarks to compare the target company's performance against its industry peers. \n"
    "This comparative analysis should inform whether the company is outperforming, underperforming, or in line with sector expectations.\n\n"
    "📌 Sector & Industry Context:\n"
    "Your assessment must consider the company's sector and industry characteristics. \n"
    "Benchmark the financial metrics against typical norms for the sector. \n"
    "For example, high leverage may be acceptable in utilities or telecom, \n"
    "while margin strength may be more critical in software or consumer tech. \n"
    "Use the business description to understand the company's operating model and tailor your analysis accordingly.\n\n"
    "Provide a concise, sector-aware classification of the stock's regime: bull or bear.\n"
)


# ---------------------------------------------------------------------------
# Topic-specific metric blocks
# Each block lists only the metrics relevant to that topic, with formulas.
# Reused verbatim inside build_topic_prompt() — edit here to propagate everywhere.
# ---------------------------------------------------------------------------

_TOPIC_METRICS = {
    "liquidity": """\
Scored metrics (1–5 scale, feed composite score):
    -CurrentRatio: current assets / current liabilities
    -QuickRatio: (current assets - inventory) / current liabilities
    -CashRatio: cash and equivalents / current liabilities
    -WorkingCapitalRatio: working capital / current assets

Extended metrics (unscored diagnostics):
    -ReceivablesTurnover: total revenue / accounts receivable
    -DSO (Days Sales Outstanding): 365 / ReceivablesTurnover — lower is better
    -InventoryTurnover: cost of revenue / inventory
    -DIO (Days Inventory Outstanding): 365 / InventoryTurnover — lower is better
    -PayablesTurnover: cost of revenue / accounts payable
    -DPO (Days Payable Outstanding): 365 / PayablesTurnover — higher is better
    -CCC (Cash Conversion Cycle): DSO + DIO - DPO — lower is better\
""",

    "solvency": """\
Scored metrics (1–5 scale, feed composite score):
    -DebtToEquity: total debt / total equity (lower is better)
    -DebtRatio: total debt / total assets (lower is better)
    -EquityRatio: total equity / total assets
    -NetDebtToEBITDA: net debt / ebitda (lower is better)
    -InterestCoverage: ebit / interest expense

Extended metrics (unscored diagnostics):
    -DebtGrowth: year-over-year percent change in total debt — rapid growth signals rising leverage risk\
""",

    "profitability": """\
Scored metrics (1–5 scale, feed composite score):
    -GrossMargin: gross profit / total revenue
    -OperatingMargin: operating income / total revenue
    -NetProfitMargin: net income / total revenue
    -EBITDAMargin: ebitda / total revenue
    -ROA: net income / total assets
    -ROE: net income / total equity
    -ROIC: ebit * (1 - tax_rate) / invested_capital

Extended metrics (unscored diagnostics):
    -Accruals: (net_income - operating_cash_flow) / total_assets
        High positive Accruals signal earnings are not cash-backed (earnings quality risk).
        Low or negative Accruals indicate cash-backed earnings.\
""",

    "efficiency": """\
Scored metrics (1–5 scale, feed composite score):
    -AssetTurnover: total revenue / total assets

Extended metrics (unscored diagnostics):
    -ReceivablesTurnover: total revenue / accounts receivable
    -DSO (Days Sales Outstanding): 365 / ReceivablesTurnover — lower is better
    -InventoryTurnover: cost of revenue / inventory
    -DIO (Days Inventory Outstanding): 365 / InventoryTurnover — lower is better
    -PayablesTurnover: cost of revenue / accounts payable
    -DPO (Days Payable Outstanding): 365 / PayablesTurnover — higher is better
    -CCC (Cash Conversion Cycle): DSO + DIO - DPO — lower is better\
""",

    "cash_flow": """\
Scored metrics (1–5 scale, feed composite score):
    -FCFToRevenue: free cash flow / total revenue
    -FCFYield: free cash flow / market capitalization
    -FCFtoDebt: free cash flow / total debt
    -OCFRatio: operating cash flow / current liabilities
    -FCFMargin: free cash flow / total revenue
    -CashConversion: operating cash flow / net income
    -CapexRatio: capital expenditure / operating cash flow (lower is better)

Extended metrics (unscored diagnostics):
    -FCFGrowth: year-over-year percent change in free cash flow
    -CapexToDepreciation: capital expenditure / depreciation
        Values well above 1.0 indicate heavy growth reinvestment.
        Values near 1.0 suggest maintenance capex only.\
""",

    "growth": """\
Extended metrics (unscored — growth rates are time-differential, not threshold-scored):
    -RevenueGrowth: (revenue_t / revenue_t-1) - 1
    -NetIncomeGrowth: (net_income_t / net_income_t-1) - 1
    -FCFGrowth: (fcf_t / fcf_t-1) - 1
    -DebtGrowth: year-over-year percent change in total debt (included for context)
    -Dilution: year-over-year percent change in shares outstanding
        Positive = dilutive (reduces per-share value); negative = accretive (buybacks).\
""",

    "red_flags": """\
Cash-flow quality flags (raw_red_flags):
    Triggered when: free cash flow < 0, operating cash flow < 0,
    or EBITDA materially exceeds operating cash flow (accrual gap).

Threshold-based flags (red_flags):
    Triggered when: GrossMargin < 0, OperatingMargin < 0, NetProfitMargin < 0,
    ROA < 0, ROE < 0, or DebtToEquity above sector-specific threshold.

Extended quality ratios (unscored diagnostics):
    -Accruals: (net_income - operating_cash_flow) / total_assets
        High positive values signal earnings quality risk.
    -DebtGrowth: year-over-year change in total debt — rapid growth signals leverage risk.
    -Dilution: year-over-year change in shares outstanding — persistent positive values erode per-share value.
    -CapexToDepreciation: capital expenditure / depreciation
        Values well above 1.0 signal heavy reinvestment that may compress future FCF.\
""",
}

# Quantitative overview block: composite scores are the primary source;
# all other payloads are provided for cross-referencing.
_TOPIC_METRICS["quantitative_overview"] = (
    "Composite Scores (primary source — read these first):\n"
    "    The composite_scores payload contains the weighted composite score (1–5 scale)\n"
    "    and per-dimension sub-scores across all available time periods.\n"
    "    Higher scores = stronger fundamentals. Use these to assess trend and profile.\n"
    "    Composite score ranges: 1 = Weak, 3 = Adequate, 5 = Strong.\n"
    "    Four metrics use inverse scoring (lower = higher score):\n"
    "    DebtToEquity, DebtRatio, NetDebtToEBITDA, CapexRatio.\n\n"
    + _FINANCIAL_METRICS_BLOCK
    + "\n\nEvaluation Metrics (not in composite — use for valuation context):\n"
    "    -bvps: total equity / shares outstanding\n"
    "    -fcf_per_share: free cash flow / shares outstanding\n"
    "    -eps: earning per share\n"
    "    -P/E: current stock price / eps\n"
    "    -P/B: current stock price / bvps\n"
    "    -P/FCF: current stock price / fcf_per_share\n"
    "    -EarningsYield: eps / current stock price\n"
    "    -FCFYield: free cash flow / market capitalization\n\n"
    + _EXTENDED_METRICS_BLOCK
    + "\n\n"
    + _RED_FLAGS_BLOCK
)

# Comprehensive block: all 24 scored + all 14 extended, grouped by topic.
# Reuses _FINANCIAL_METRICS_BLOCK and _EXTENDED_METRICS_BLOCK rather than duplicating.
_TOPIC_METRICS["comprehensive"] = (
    _FINANCIAL_METRICS_BLOCK
    + "\n\nEvaluation metrics (not scored, not in composite):\n"
    + _EVAL_METRICS_BLOCK.replace("Evaluation metrics provided are the following:\n", "")
    + "\n\n"
    + _EXTENDED_METRICS_BLOCK
)

# ---------------------------------------------------------------------------
# Rating / classification guidance shared across topic prompts
# ---------------------------------------------------------------------------

_TOPIC_RATING_GUIDE = {
    "liquidity":      "'strong' / 'adequate' / 'weak' — ability to meet short-term obligations",
    "solvency":       "'strong' / 'adequate' / 'weak' — long-term debt sustainability",
    "profitability":  "'strong' / 'adequate' / 'weak' — margin quality and capital returns",
    "efficiency":     "'strong' / 'adequate' / 'weak' — asset utilisation and working capital speed",
    "cash_flow":      "'strong' / 'adequate' / 'weak' — FCF generation and cash conversion quality",
    "growth":         "'accelerating' / 'stable' / 'decelerating' / 'declining' — multi-year revenue, income, and FCF trajectory",
    "red_flags":      "'none' / 'low' / 'moderate' / 'high' — combined severity of all detected warnings",
    "quantitative_overview": (
        "overall_rating: 'strong' / 'adequate' / 'weak'; "
        "composite_trend: 'improving' / 'stable' / 'deteriorating'; "
        "data_completeness: 'complete' / 'partial' / 'sparse'"
    ),
    "comprehensive":  (
        "regime: 'bull' / 'bear'; "
        "evaluation: 'overvalued' / 'undervalued' / 'fair'; "
        "each sub-model uses its own rating/trajectory/severity scale"
    ),
}

# ---------------------------------------------------------------------------
# Topic prompt factory
# ---------------------------------------------------------------------------

_VALID_TOPICS = frozenset(_TOPIC_METRICS.keys())


def build_topic_prompt(topic: str) -> str:
    """
    Build a focused system prompt for a single topic-model assessment.

    Args:
        topic: One of 'liquidity', 'solvency', 'profitability', 'efficiency',
               'cash_flow', 'growth', 'red_flags', 'comprehensive'.

    Returns:
        A system prompt string aligned with the corresponding Pydantic model
        in pydantic_models.py.

    Raises:
        ValueError: If topic is not in the valid set.

    Invariant:
        Metric definitions are pulled from _TOPIC_METRICS — editing those
        constants propagates to every topic prompt automatically.
    """
    if topic not in _VALID_TOPICS:
        raise ValueError(
            f"Unknown topic {topic!r}. Valid topics: {sorted(_VALID_TOPICS)}"
        )

    topic_label = topic.replace("_", " ")
    rating_guide = _TOPIC_RATING_GUIDE[topic]
    metrics_block = _TOPIC_METRICS[topic]

    if topic == "comprehensive":
        role = (
            "You are a fundamental analysis specialist. "
            "Your task is to produce a comprehensive, multi-dimensional stock assessment "
            "covering all seven metric groups: liquidity, solvency, profitability, efficiency, "
            "cash flow, growth, and red flags."
        )
        task = (
            "Based on the full set of scored and extended metrics provided, produce a "
            "ComprehensiveStockAssessment containing:\n"
            "  - An overall regime classification (bull / bear) with rationale\n"
            "  - A valuation classification (overvalued / undervalued / fair)\n"
            "  - Seven nested topic assessments — one per metric group\n\n"
            "For each topic assessment, apply the following rating scale:\n"
            f"  {rating_guide}\n\n"
            "Consider sector context: norms differ across industries "
            "(e.g. higher leverage is acceptable in utilities; thin margins are normal in retail)."
        )
    else:
        role = (
            f"You are a {topic_label} analysis specialist in fundamental stock analysis. "
            f"Your task is to produce a focused, evidence-based {topic_label} assessment "
            "using only the metrics provided."
        )
        task = (
            f"Based on the {topic_label} metrics provided, produce a structured assessment.\n\n"
            f"Classification scale: {rating_guide}.\n\n"
            "Populate every required field:\n"
            "  - rating / trajectory / severity: choose the single best-fit value from the allowed set\n"
            "  - rationale: concise justification drawing on the metrics listed below\n"
            "  - topic-specific field: detailed narrative on the secondary dimension of this topic\n"
            "  - concerns: specific anomalies or risks not captured by the rating; "
            "set to null if none exist\n\n"
            "Consider sector context where relevant — rating thresholds vary by industry."
        )

    return (
        f"{role}\n\n"
        f"{task}\n\n"
        f"Metrics provided:\n\n"
        f"{metrics_block}\n"
    )


# ---------------------------------------------------------------------------
# Topic prompt constants — one per pydantic_models topic model
# ---------------------------------------------------------------------------

system_prompt_liquidity             = build_topic_prompt("liquidity")
system_prompt_solvency              = build_topic_prompt("solvency")
system_prompt_profitability         = build_topic_prompt("profitability")
system_prompt_efficiency            = build_topic_prompt("efficiency")
system_prompt_cash_flow             = build_topic_prompt("cash_flow")
system_prompt_growth                = build_topic_prompt("growth")
system_prompt_red_flags             = build_topic_prompt("red_flags")
system_prompt_quantitative_overview = build_topic_prompt("quantitative_overview")
system_prompt_comprehensive         = build_topic_prompt("comprehensive")
