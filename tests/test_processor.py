"""
Unit tests for FundamentalTraderAssistant.

All tests use a synthetic 3-row DataFrame — no network calls, no .env required.

Covered:
  1. compute_metrics() produces all 24 expected columns
  2. compute_extended_metrics() produces all 14 expected unscored columns
  3. compute_extended_metrics() computes correct growth values (known pct_change inputs)
  4. compute_extended_metrics() is time-order-invariant (reversed input → same result)
  5. score_metric() threshold buckets for new scored metrics
  6. Inverse-scored metrics (DebtRatio, NetDebtToEBITDA, CapexRatio, DebtToEquity)
  7. evaluate() returns all 6 keys with non-empty DataFrames
"""

import unittest
import numpy as np
import pandas as pd

from financialtools.processor import FundamentalTraderAssistant, SCORED_METRICS


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ALL_SCORED_COLS = [
    # original 11
    "GrossMargin", "OperatingMargin", "NetProfitMargin", "EBITDAMargin",
    "ROA", "ROE", "FCFToRevenue", "FCFYield", "FCFtoDebt",
    "DebtToEquity", "CurrentRatio",
    # extended 13
    "QuickRatio", "CashRatio", "WorkingCapitalRatio",
    "DebtRatio", "EquityRatio", "NetDebtToEBITDA", "InterestCoverage",
    "ROIC",
    "AssetTurnover",
    "OCFRatio", "FCFMargin", "CashConversion", "CapexRatio",
]

ALL_EXTENDED_COLS = [
    "ReceivablesTurnover", "DSO", "InventoryTurnover", "DIO",
    "PayablesTurnover", "DPO", "CCC",
    "RevenueGrowth", "NetIncomeGrowth", "FCFGrowth",
    "Accruals", "DebtGrowth", "Dilution", "CapexToDepreciation",
]


def _make_data(
    revenues=(100.0, 120.0, 150.0),
    net_incomes=(10.0, 12.0, 15.0),
    fcfs=(8.0, 10.0, 12.0),
    ticker="TEST",
    times=("2022", "2023", "2024"),
) -> pd.DataFrame:
    """
    Build a synthetic merged DataFrame covering every column needed by
    compute_metrics() and compute_extended_metrics().

    Keyword args allow callers to pin specific values for growth-rate assertions.
    """
    n = len(times)
    rev = list(revenues)
    ni  = list(net_incomes)
    fcf = list(fcfs)

    return pd.DataFrame({
        "ticker": ticker,
        "time":   list(times),
        # Income statement
        "total_revenue":                    rev,
        "gross_profit":                     [r * 0.6 for r in rev],
        "operating_income":                 [r * 0.2 for r in rev],
        "net_income_common_stockholders":   ni,
        "ebitda":                           [r * 0.3 for r in rev],
        "ebit":                             [r * 0.25 for r in rev],
        "diluted_eps":                      [n_ / 100 for n_ in ni],
        "interest_expense_non_operating":   [r * 0.01 for r in rev],
        "tax_rate_for_calcs":               [0.21] * n,
        # Balance sheet
        "total_assets":                     [r * 2.0 for r in rev],
        "total_debt":                       [r * 0.5 for r in rev],
        "common_stock_equity":              [r * 1.2 for r in rev],
        "current_assets":                   [r * 0.8 for r in rev],
        "current_liabilities":              [r * 0.4 for r in rev],
        "inventory":                        [r * 0.1 for r in rev],
        "accounts_receivable":              [r * 0.15 for r in rev],
        "accounts_payable":                 [r * 0.08 for r in rev],
        "cash_and_cash_equivalents":        [r * 0.2 for r in rev],
        "working_capital":                  [r * 0.4 for r in rev],
        "net_debt":                         [r * 0.3 for r in rev],
        "invested_capital":                 [r * 1.5 for r in rev],
        "ordinary_shares_number":           [1000.0] * n,
        # Cash flow
        "free_cash_flow":                   fcf,
        "operating_cash_flow":              [f * 1.2 for f in fcf],
        "capital_expenditure":              [-r * 0.05 for r in rev],
        "depreciation_amortization_depletion": [r * 0.04 for r in rev],
        "cost_of_revenue":                  [r * 0.4 for r in rev],
        # Market / other
        "marketcap":                        [r * 5.0 for r in rev],
        "currentprice":                     [20.0] * n,
    })


def _make_weights(sector: str = "Technology Services") -> pd.DataFrame:
    """Return a weights DataFrame covering all 24 scored metrics."""
    from financialtools.config import sector_metric_weights
    items = sector_metric_weights[sector].items()
    df = pd.DataFrame(list(items), columns=["metrics", "weights"])
    df["sector"] = sector
    return df


def _make_fta(
    revenues=(100.0, 120.0, 150.0),
    net_incomes=(10.0, 12.0, 15.0),
    fcfs=(8.0, 10.0, 12.0),
    times=("2022", "2023", "2024"),
    sector: str = "Technology Services",
) -> FundamentalTraderAssistant:
    data    = _make_data(revenues=revenues, net_incomes=net_incomes, fcfs=fcfs, times=times)
    weights = _make_weights(sector)
    return FundamentalTraderAssistant(data, weights)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComputeMetricsColumns(unittest.TestCase):
    """compute_metrics() must return all 24 scored metric columns."""

    def setUp(self):
        self.fta = _make_fta()

    def test_returns_all_24_scored_columns(self):
        m = self.fta.compute_metrics()
        for col in ALL_SCORED_COLS:
            self.assertIn(col, m.columns, f"Missing scored column: {col}")

    def test_column_count(self):
        m = self.fta.compute_metrics()
        # ticker + time + sector + 24 metrics = 27
        self.assertEqual(len(m.columns), 27)

    def test_scored_metrics_constant_matches(self):
        """SCORED_METRICS constant must list exactly the 24 expected names."""
        self.assertEqual(set(SCORED_METRICS), set(ALL_SCORED_COLS))


class TestComputeExtendedMetricsColumns(unittest.TestCase):
    """compute_extended_metrics() must return all 14 unscored columns."""

    def setUp(self):
        self.fta = _make_fta()

    def test_returns_all_14_unscored_columns(self):
        ext = self.fta.compute_extended_metrics()
        for col in ALL_EXTENDED_COLS:
            self.assertIn(col, ext.columns, f"Missing extended column: {col}")

    def test_always_has_ticker_time_sector(self):
        ext = self.fta.compute_extended_metrics()
        for col in ("ticker", "time", "sector"):
            self.assertIn(col, ext.columns)


class TestGrowthValues(unittest.TestCase):
    """compute_extended_metrics() growth rates must match known pct_change values."""

    def test_revenue_growth(self):
        # revenues: 100 → 120 → 150
        # pct_change: NaN, 0.20, 0.25
        fta = _make_fta(revenues=(100.0, 120.0, 150.0))
        ext = fta.compute_extended_metrics()
        growth = ext["RevenueGrowth"].tolist()
        self.assertTrue(np.isnan(growth[0]))
        self.assertAlmostEqual(growth[1], 0.20, places=6)
        self.assertAlmostEqual(growth[2], 0.25, places=6)

    def test_fcf_growth(self):
        # fcfs: 8 → 10 → 12; pct_change: NaN, 0.25, 0.20
        fta = _make_fta(fcfs=(8.0, 10.0, 12.0))
        ext = fta.compute_extended_metrics()
        growth = ext["FCFGrowth"].tolist()
        self.assertTrue(np.isnan(growth[0]))
        self.assertAlmostEqual(growth[1], 0.25, places=6)
        self.assertAlmostEqual(growth[2], 0.20, places=6)


class TestExtendedMetricsTimeOrdering(unittest.TestCase):
    """Growth rates must be identical whether input rows are sorted or reversed."""

    def test_reversed_input_same_growth(self):
        fta_fwd = _make_fta(
            revenues=(100.0, 120.0, 150.0),
            times=("2022", "2023", "2024"),
        )
        fta_rev = _make_fta(
            revenues=(150.0, 120.0, 100.0),   # reversed order
            times=("2024", "2023", "2022"),
        )
        ext_fwd = fta_fwd.compute_extended_metrics().sort_values("time").reset_index(drop=True)
        ext_rev = fta_rev.compute_extended_metrics().sort_values("time").reset_index(drop=True)

        pd.testing.assert_series_equal(
            ext_fwd["RevenueGrowth"].reset_index(drop=True),
            ext_rev["RevenueGrowth"].reset_index(drop=True),
            check_names=False,
        )


class TestScoreMetricThresholds(unittest.TestCase):
    """score_metric() must map values to the expected 1–5 bucket."""

    def _score_one(self, metric: str, value: float) -> int:
        fta = _make_fta()
        df = pd.DataFrame({"metrics": [metric], "value": [value]})
        result = fta.score_metric(df)
        return int(result["score"].iloc[0])

    # ── QuickRatio: [0.5, 0.8, 1.0, 1.5] ─────────────────────────────────
    def test_quick_ratio_below_first_threshold(self):
        self.assertEqual(self._score_one("QuickRatio", 0.3), 1)

    def test_quick_ratio_between_2nd_3rd(self):
        self.assertEqual(self._score_one("QuickRatio", 0.9), 3)

    def test_quick_ratio_above_last(self):
        self.assertEqual(self._score_one("QuickRatio", 2.0), 5)

    # ── InterestCoverage: [1.5, 3.0, 5.0, 10.0] ──────────────────────────
    def test_interest_coverage_score_4(self):
        self.assertEqual(self._score_one("InterestCoverage", 7.0), 4)

    # ── ROIC: [0.05, 0.10, 0.15, 0.20] ───────────────────────────────────
    def test_roic_score_2(self):
        self.assertEqual(self._score_one("ROIC", 0.07), 2)

    def test_roic_score_5(self):
        self.assertEqual(self._score_one("ROIC", 0.25), 5)

    # ── AssetTurnover: [0.3, 0.6, 1.0, 1.5] ──────────────────────────────
    def test_asset_turnover_score_1(self):
        self.assertEqual(self._score_one("AssetTurnover", 0.1), 1)

    # ── OCFRatio: [0.1, 0.2, 0.4, 0.6] ───────────────────────────────────
    def test_ocf_ratio_score_3(self):
        self.assertEqual(self._score_one("OCFRatio", 0.25), 3)

    # ── NaN → neutral score 3 ─────────────────────────────────────────────
    def test_nan_returns_neutral(self):
        self.assertEqual(self._score_one("ROIC", float("nan")), 3)

    # ── Unknown metric → neutral score 3 ─────────────────────────────────
    def test_unknown_metric_returns_neutral(self):
        self.assertEqual(self._score_one("SomeFutureMetric", 99.9), 3)


class TestInverseScoring(unittest.TestCase):
    """Inverse-scored metrics must assign low scores to high values."""

    def _score_one(self, metric: str, value: float) -> int:
        fta = _make_fta()
        df = pd.DataFrame({"metrics": [metric], "value": [value]})
        return int(fta.score_metric(df)["score"].iloc[0])

    def test_debt_ratio_low_value_gets_high_score(self):
        # DebtRatio 0.1 < 0.2 (first threshold) → digitize=0+1=1 → 6-1=5
        self.assertEqual(self._score_one("DebtRatio", 0.1), 5)

    def test_debt_ratio_high_value_gets_low_score(self):
        # DebtRatio 0.9 > 0.8 (last threshold) → digitize=4+1=5 → 6-5=1
        self.assertEqual(self._score_one("DebtRatio", 0.9), 1)

    def test_net_debt_to_ebitda_low_is_better(self):
        # NetDebtToEBITDA 0.5 < 1.0 → score 5
        self.assertEqual(self._score_one("NetDebtToEBITDA", 0.5), 5)

    def test_capex_ratio_low_is_better(self):
        # CapexRatio 0.05 < 0.1 → score 5
        self.assertEqual(self._score_one("CapexRatio", 0.05), 5)

    def test_debt_to_equity_still_inverse(self):
        # Original inverse metric must still work after refactor
        high_dte = self._score_one("DebtToEquity", 2.5)  # above last threshold → score 1
        low_dte  = self._score_one("DebtToEquity", 0.3)  # below first threshold → score 5
        self.assertGreater(low_dte, high_dte)


class TestEvaluateReturnsAllKeys(unittest.TestCase):
    """evaluate() must always return all 6 keys with non-empty DataFrames."""

    EXPECTED_KEYS = {
        "metrics", "eval_metrics", "composite_scores",
        "raw_red_flags", "red_flags", "extended_metrics",
    }

    def test_all_keys_present(self):
        fta = _make_fta()
        result = fta.evaluate()
        self.assertEqual(set(result.keys()), self.EXPECTED_KEYS)

    def test_metrics_not_empty(self):
        fta = _make_fta()
        result = fta.evaluate()
        self.assertFalse(result["metrics"].empty)

    def test_composite_scores_not_empty(self):
        fta = _make_fta()
        result = fta.evaluate()
        self.assertFalse(result["composite_scores"].empty)

    def test_extended_metrics_not_empty(self):
        fta = _make_fta()
        result = fta.evaluate()
        self.assertFalse(result["extended_metrics"].empty)

    def test_extended_metrics_has_correct_columns(self):
        fta = _make_fta()
        ext = fta.evaluate()["extended_metrics"]
        for col in ALL_EXTENDED_COLS:
            self.assertIn(col, ext.columns, f"Missing column in extended_metrics: {col}")

    def test_metrics_has_24_metric_columns(self):
        fta = _make_fta()
        m = fta.evaluate()["metrics"]
        id_cols = {"ticker", "time", "sector"}
        metric_cols = [c for c in m.columns if c not in id_cols]
        self.assertEqual(len(metric_cols), 24)


class TestMissingOptionalColumns(unittest.TestCase):
    """Metrics backed by optional columns must be NaN, not raise."""

    def test_missing_inventory_gives_nan_quick_ratio(self):
        data = _make_data()
        data = data.drop(columns=["inventory"])
        weights = _make_weights()
        fta = FundamentalTraderAssistant(data, weights)
        m = fta.compute_metrics()
        self.assertTrue(m["QuickRatio"].isna().all())

    def test_missing_invested_capital_gives_nan_roic(self):
        data = _make_data()
        data = data.drop(columns=["invested_capital"])
        weights = _make_weights()
        fta = FundamentalTraderAssistant(data, weights)
        m = fta.compute_metrics()
        self.assertTrue(m["ROIC"].isna().all())

    def test_missing_ebit_gives_nan_interest_coverage(self):
        data = _make_data()
        data = data.drop(columns=["ebit"])
        weights = _make_weights()
        fta = FundamentalTraderAssistant(data, weights)
        m = fta.compute_metrics()
        self.assertTrue(m["InterestCoverage"].isna().all())


if __name__ == "__main__":
    unittest.main()
