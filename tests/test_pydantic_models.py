"""
Unit tests for pydantic_models.py — validated LLM output schemas.

No network calls, no .env required.

Covered:
  1. StockRegimeAssessment accepts "bull", "bear", "neutral"
  2. StockRegimeAssessment rejects invalid regime values
  3. ComprehensiveStockAssessment accepts "bull", "bear", "neutral"
  4. ComprehensiveStockAssessment rejects invalid regime values
"""

import unittest
from pydantic import ValidationError

from financialtools.pydantic_models import (
    StockRegimeAssessment,
    ComprehensiveStockAssessment,
    LiquidityAssessment,
    SolvencyAssessment,
    ProfitabilityAssessment,
    EfficiencyAssessment,
    CashFlowAssessment,
    GrowthAssessment,
    RedFlagsAssessment,
)


def _minimal_regime(regime: str) -> dict:
    return {
        "ticker": "AAPL",
        "regime": regime,
        "regime_rationale": "test",
        "metrics_movement": "test",
        "evaluation": "fair",
        "evaluation_rationale": "test",
        "market_comparison": "test",
    }


def _minimal_comprehensive(regime: str) -> dict:
    liquidity = {"rating": "adequate", "rationale": "ok", "working_capital_efficiency": "ok"}
    solvency  = {"rating": "adequate", "rationale": "ok", "debt_trend": "ok"}
    profit    = {"rating": "adequate", "rationale": "ok", "earnings_quality": "ok"}
    eff       = {"rating": "adequate", "rationale": "ok", "working_capital_chain": "ok"}
    cf        = {"rating": "adequate", "rationale": "ok", "capital_allocation": "ok"}
    growth    = {"trajectory": "stable", "rationale": "ok", "dilution_impact": "ok"}
    rf        = {"severity": "none", "rationale": "ok"}
    return {
        "ticker": "AAPL",
        "regime": regime,
        "regime_rationale": "test",
        "evaluation": "fair",
        "liquidity": liquidity,
        "solvency": solvency,
        "profitability": profit,
        "efficiency": eff,
        "cash_flow": cf,
        "growth": growth,
        "red_flags": rf,
    }


class TestStockRegimeAssessmentLiteral(unittest.TestCase):

    def test_bull_accepted(self):
        m = StockRegimeAssessment(**_minimal_regime("bull"))
        self.assertEqual(m.regime, "bull")

    def test_bear_accepted(self):
        m = StockRegimeAssessment(**_minimal_regime("bear"))
        self.assertEqual(m.regime, "bear")

    def test_neutral_accepted(self):
        # P1-2 regression: "neutral" must be a valid regime value
        m = StockRegimeAssessment(**_minimal_regime("neutral"))
        self.assertEqual(m.regime, "neutral")

    def test_invalid_regime_rejected(self):
        with self.assertRaises(ValidationError):
            StockRegimeAssessment(**_minimal_regime("sideways"))

    def test_empty_regime_rejected(self):
        with self.assertRaises(ValidationError):
            StockRegimeAssessment(**_minimal_regime(""))


class TestComprehensiveStockAssessmentLiteral(unittest.TestCase):

    def test_bull_accepted(self):
        m = ComprehensiveStockAssessment(**_minimal_comprehensive("bull"))
        self.assertEqual(m.regime, "bull")

    def test_bear_accepted(self):
        m = ComprehensiveStockAssessment(**_minimal_comprehensive("bear"))
        self.assertEqual(m.regime, "bear")

    def test_neutral_accepted(self):
        # P1-2 regression: "neutral" must be a valid regime value
        m = ComprehensiveStockAssessment(**_minimal_comprehensive("neutral"))
        self.assertEqual(m.regime, "neutral")

    def test_invalid_regime_rejected(self):
        with self.assertRaises(ValidationError):
            ComprehensiveStockAssessment(**_minimal_comprehensive("mixed"))


if __name__ == "__main__":
    unittest.main()
