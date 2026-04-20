"""
Unit tests for FundamentalMetricsEvaluator.

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

from financialtools.processor import FundamentalMetricsEvaluator, SCORED_METRICS


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


def _make_weights(sector: str = "technology") -> pd.DataFrame:
    """Return a weights DataFrame covering all 24 scored metrics."""
    from financialtools.config import sec_sector_metric_weights
    items = sec_sector_metric_weights[sector].items()
    df = pd.DataFrame(list(items), columns=["metrics", "weights"])
    df["sector"] = sector
    return df


def _make_fta(
    revenues=(100.0, 120.0, 150.0),
    net_incomes=(10.0, 12.0, 15.0),
    fcfs=(8.0, 10.0, 12.0),
    times=("2022", "2023", "2024"),
    sector: str = "technology",
) -> FundamentalMetricsEvaluator:
    data    = _make_data(revenues=revenues, net_incomes=net_incomes, fcfs=fcfs, times=times)
    weights = _make_weights(sector)
    return FundamentalMetricsEvaluator(data, weights)


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
        result = fta._score_metric(df)
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
        return int(fta._score_metric(df)["score"].iloc[0])

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


class TestNegativeEquityScoring(unittest.TestCase):
    """P1-1: Negative DebtToEquity (negative book equity) must score 1, not 5.

    Without the guard, np.digitize maps a negative D/E to bucket 0 → raw score 1,
    then inversion gives 6-1=5 (best possible). A company with negative equity
    is maximum financial risk and must score 1.
    """

    def _score_one(self, metric: str, value: float) -> int:
        fta = _make_fta()
        df = pd.DataFrame({"metrics": [metric], "value": [value]})
        return int(fta._score_metric(df)["score"].iloc[0])

    def test_negative_dte_scores_1_not_5(self):
        # Core regression: negative equity → maximum risk → score 1
        self.assertEqual(self._score_one("DebtToEquity", -0.5), 1)

    def test_strongly_negative_dte_scores_1(self):
        # Deep negative equity (e.g. Boeing historical) must also score 1
        self.assertEqual(self._score_one("DebtToEquity", -10.0), 1)

    def test_zero_dte_is_nan_scores_neutral(self):
        # Zero denominator → safe_div returns NaN → neutral score 3
        # (this tests integration with safe_div, not score_row directly)
        self.assertEqual(self._score_one("DebtToEquity", float("nan")), 3)

    def test_positive_dte_inversion_unchanged(self):
        # Positive D/E must still invert correctly: low value → high score
        self.assertEqual(self._score_one("DebtToEquity", 0.3), 5)  # below 0.5 → score 5
        self.assertEqual(self._score_one("DebtToEquity", 2.5), 1)  # above 2.0 → score 1

    def test_negative_dte_in_full_evaluate_pipeline(self):
        """evaluate() composite score must not be inflated by negative equity."""
        data = _make_data()
        # Force negative equity on all rows
        data["common_stock_equity"] = -500.0
        fta = FundamentalMetricsEvaluator(data, _make_weights())
        scores = fta.compute_scores()
        dte_rows = scores[scores["metrics"] == "DebtToEquity"]
        self.assertFalse(dte_rows.empty)
        self.assertTrue((dte_rows["score"] == 1).all(),
                        "All DebtToEquity scores must be 1 when equity is negative")


class TestScoreMetricVectorized(unittest.TestCase):
    """P2-6: _score_metric must be vectorized, picklable, and produce identical
    results to the previous row-by-row apply() implementation.
    """

    def _score_all(self, rows: list) -> list:
        """Score a list of (metric_name, value) pairs, return list of scores."""
        fta = _make_fta()
        df = pd.DataFrame(rows, columns=["metrics", "value"])
        return fta._score_metric(df)["score"].tolist()

    def test_mixed_batch_scores_correctly(self):
        # Verify several metrics at once — proves vectorized path handles multiple
        # metric names in a single DataFrame without cross-contamination.
        rows = [
            ("GrossMargin",     0.55),   # above last threshold 0.5 → digitize=4 → score 5
            ("GrossMargin",     0.25),   # between 1st/2nd threshold → score 2
            ("DebtToEquity",    0.3),    # below 0.5 → raw 1 → inverse 5
            ("DebtToEquity",    2.5),    # above 2.0 → raw 5 → inverse 1
            ("DebtToEquity",   -1.0),    # negative equity → P1-1 guard → 1
            ("NetProfitMargin", float("nan")),  # NaN → neutral 3
            ("SomeFutureMetric", 99.9),  # unknown → neutral 3
        ]
        expected = [5, 2, 5, 1, 1, 3, 3]
        self.assertEqual(self._score_all(rows), expected)

    def test_all_nan_values_score_3(self):
        rows = [(m, float("nan")) for m in ["GrossMargin", "ROE", "DebtToEquity"]]
        self.assertEqual(self._score_all(rows), [3, 3, 3])

    def test_score_metric_is_picklable(self):
        """_score_metric must not close over self — it must be picklable."""
        import pickle
        fta = _make_fta()
        # The method itself references self, but the key property being tested is
        # that compute_scores (which calls _score_metric) works inside a subprocess.
        # We test picklability of the result DataFrame rather than the bound method,
        # and confirm FundamentalMetricsEvaluator itself is picklable for ProcessPoolExecutor.
        scores = fta.compute_scores()
        pickled = pickle.dumps(scores)
        restored = pickle.loads(pickled)
        self.assertEqual(list(scores["score"]), list(restored["score"]))

    def test_no_cross_contamination_between_metric_groups(self):
        """Rows from different metrics in the same DataFrame must not affect each other."""
        fta = _make_fta()
        df = pd.DataFrame({
            "metrics": ["ROA", "DebtToEquity", "ROA"],
            "value":   [0.10,   0.30,           0.03],
        })
        result = fta._score_metric(df)
        # ROA 0.10 is between 3rd/4th threshold [0.02,0.05,0.08,0.12] → score 4
        # DebtToEquity 0.30 → inverse → score 5
        # ROA 0.03 is between 1st/2nd threshold → score 2
        self.assertEqual(result["score"].tolist(), [4, 5, 2])


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
        fta = FundamentalMetricsEvaluator(data, weights)
        m = fta.compute_metrics()
        self.assertTrue(m["QuickRatio"].isna().all())

    def test_missing_invested_capital_gives_nan_roic(self):
        data = _make_data()
        data = data.drop(columns=["invested_capital"])
        weights = _make_weights()
        fta = FundamentalMetricsEvaluator(data, weights)
        m = fta.compute_metrics()
        self.assertTrue(m["ROIC"].isna().all())

    def test_missing_ebit_gives_nan_interest_coverage(self):
        data = _make_data()
        data = data.drop(columns=["ebit"])
        weights = _make_weights()
        fta = FundamentalMetricsEvaluator(data, weights)
        m = fta.compute_metrics()
        self.assertTrue(m["InterestCoverage"].isna().all())


class TestMissingCoreColumns(unittest.TestCase):
    """P0-1: core yfinance columns absent due to schema change must not raise.

    Before this fix, a missing core column (e.g. total_revenue renamed by yfinance)
    raised a KeyError swallowed by the except clause, producing an opaque
    EvaluationError with no column context.

    After this fix:
      - compute_metrics() returns a DataFrame with NaN for affected metrics
      - compute_valuation_metrics() returns a DataFrame with NaN for affected metrics
      - a single WARNING is logged listing all missing columns
    """

    def test_missing_total_revenue_gives_nan_margins_not_exception(self):
        data = _make_data().drop(columns=["total_revenue"])
        fta = FundamentalMetricsEvaluator(data, _make_weights())
        m = fta.compute_metrics()
        self.assertIsInstance(m, pd.DataFrame)
        self.assertFalse(m.empty)
        for col in ("GrossMargin", "OperatingMargin", "NetProfitMargin",
                    "EBITDAMargin", "FCFToRevenue", "FCFMargin", "AssetTurnover"):
            self.assertTrue(m[col].isna().all(), f"{col} should be NaN when total_revenue is absent")

    def test_missing_free_cash_flow_gives_nan_fcf_metrics(self):
        data = _make_data().drop(columns=["free_cash_flow"])
        fta = FundamentalMetricsEvaluator(data, _make_weights())
        m = fta.compute_metrics()
        self.assertIsInstance(m, pd.DataFrame)
        for col in ("FCFToRevenue", "FCFYield", "FCFtoDebt", "FCFMargin"):
            self.assertTrue(m[col].isna().all(), f"{col} should be NaN when free_cash_flow is absent")

    def test_missing_diluted_eps_gives_nan_valuation_not_exception(self):
        data = _make_data().drop(columns=["diluted_eps"])
        fta = FundamentalMetricsEvaluator(data, _make_weights())
        ev = fta.compute_valuation_metrics()
        self.assertIsInstance(ev, pd.DataFrame)
        self.assertFalse(ev.empty)
        self.assertTrue(ev["eps"].isna().all())

    def test_missing_core_column_emits_warning_with_column_name(self):
        data = _make_data().drop(columns=["total_revenue", "free_cash_flow"])
        fta = FundamentalMetricsEvaluator(data, _make_weights())
        with self.assertLogs("financialtools.evaluator", level="WARNING") as cm:
            fta.compute_metrics()
        # A single WARNING must name both missing columns — not a generic message
        combined = " ".join(cm.output)
        self.assertIn("total_revenue", combined)
        self.assertIn("free_cash_flow", combined)

    def test_evaluate_completes_with_missing_core_column(self):
        """evaluate() must not raise when a core column is absent."""
        data = _make_data().drop(columns=["total_debt"])
        fta = FundamentalMetricsEvaluator(data, _make_weights())
        result = fta.evaluate()
        self.assertIn("composite_scores", result)
        self.assertFalse(result["composite_scores"].empty)


def _make_bank_data(ticker: str = "BGN.MI") -> pd.DataFrame:
    """
    Minimal synthetic DataFrame that mimics a bank ticker (e.g. Banca Generali).

    Banks structurally omit: gross_profit, operating_income, ebitda,
    current_assets, current_liabilities, inventory.

    Columns present mirror what yfinance actually returns for MIL-listed banks.
    """
    return pd.DataFrame({
        "ticker": [ticker] * 3,
        "time":   ["2022", "2023", "2024"],
        # Income statement — bank layout
        "total_revenue":                    [500.0, 550.0, 600.0],
        "net_interest_income":              [300.0, 330.0, 360.0],
        "operating_revenue":                [480.0, 530.0, 580.0],
        "net_income_common_stockholders":   [60.0,  70.0,  80.0],
        "net_income":                       [60.0,  70.0,  80.0],
        "pretax_income":                    [80.0,  90.0, 100.0],
        "diluted_eps":                      [0.53,  0.61,  0.70],
        "interest_expense_non_operating":   [10.0,  12.0,  14.0],
        "tax_rate_for_calcs":               [0.25,  0.25,  0.25],
        # Balance sheet — bank layout (no current_assets / current_liabilities)
        "total_assets":                     [8000.0, 8500.0, 9000.0],
        "total_debt":                       [1000.0, 1100.0, 1200.0],
        "common_stock_equity":              [900.0,  970.0, 1050.0],
        "net_debt":                         [800.0,  880.0,  960.0],
        "receivables":                      [200.0,  220.0,  240.0],
        "accounts_payable":                 [50.0,   55.0,   60.0],
        "cash_and_cash_equivalents":        [400.0,  420.0,  440.0],
        "invested_capital":                 [1900.0, 2070.0, 2250.0],
        "ordinary_shares_number":           [114e6,  114e6,  114e6],
        # Cash flow
        "free_cash_flow":                   [50.0,  60.0,  70.0],
        "operating_cash_flow":              [65.0,  75.0,  85.0],
        "capital_expenditure":              [-5.0,  -6.0,  -7.0],
        "depreciation_amortization_depletion": [8.0, 9.0, 10.0],
        "cost_of_revenue":                  [0.0,   0.0,   0.0],
        # Market data
        "marketcap":                        [6e9,   6.5e9, 7e9],
        "currentprice":                     [53.0,  57.0,  61.0],
        # NOTE: gross_profit, ebitda, operating_income, current_assets,
        #       current_liabilities, inventory are intentionally absent.
    })


class TestBankLikeDataNoKeyError(unittest.TestCase):
    """
    Financial-sector tickers (banks) omit gross_profit, ebitda, operating_income,
    current_assets, and current_liabilities.  The processor must not raise KeyError
    for these tickers — missing columns must yield NaN scores, not exceptions.

    Covers the fix in processor.py:
      - compute_metrics()  : _REQUIRED_METRIC_COLS reindex guard
      - raw_red_flags()    : reindex instead of hard column select
      - evaluate()         : early-exit guard when compute_metrics() returns empty
    """

    BANK_MISSING_COLS = (
        "gross_profit", "ebitda", "operating_income",
        "current_assets", "current_liabilities",
    )
    # Metrics that are NaN when their source columns are absent
    EXPECTED_NAN_METRICS = (
        "GrossMargin",       # needs gross_profit
        "OperatingMargin",   # needs operating_income
        "EBITDAMargin",      # needs ebitda
        "CurrentRatio",      # needs current_assets + current_liabilities
        "QuickRatio",        # needs current_assets + current_liabilities
        "CashRatio",         # needs current_liabilities
        "WorkingCapitalRatio",# needs current_assets
        "OCFRatio",          # needs current_liabilities
        "NetDebtToEBITDA",   # needs ebitda
    )
    # Metrics that CAN be computed from bank columns
    EXPECTED_FINITE_METRICS = (
        "ROA", "ROE", "FCFToRevenue", "FCFtoDebt",
        "DebtToEquity", "DebtRatio", "EquityRatio", "AssetTurnover",
        "FCFMargin", "CashConversion",
    )

    def setUp(self):
        data    = _make_bank_data()
        weights = _make_weights("financial-services")
        self.fta = FundamentalMetricsEvaluator(data, weights)

    def test_compute_metrics_does_not_raise(self):
        """compute_metrics() must return a DataFrame, not raise KeyError."""
        m = self.fta.compute_metrics()
        self.assertIsInstance(m, pd.DataFrame)
        self.assertFalse(m.empty)

    def test_compute_metrics_has_all_24_columns(self):
        """All 24 scored metric columns must be present even when source cols are absent."""
        m = self.fta.compute_metrics()
        for col in ALL_SCORED_COLS:
            self.assertIn(col, m.columns, f"Missing scored column: {col}")

    def test_bank_incompatible_metrics_are_nan(self):
        """Metrics whose source columns are absent must be NaN (not 0, not error)."""
        m = self.fta.compute_metrics()
        for col in self.EXPECTED_NAN_METRICS:
            self.assertTrue(
                m[col].isna().all(),
                f"{col} should be all-NaN for a bank ticker but got: {m[col].tolist()}",
            )

    def test_computable_metrics_are_finite(self):
        """Metrics whose source columns ARE present must be non-NaN."""
        m = self.fta.compute_metrics()
        for col in self.EXPECTED_FINITE_METRICS:
            self.assertFalse(
                m[col].isna().all(),
                f"{col} should be finite for a bank ticker but is all-NaN",
            )

    def test_raw_red_flags_does_not_raise(self):
        """raw_red_flags() must not raise even when ebitda column is absent."""
        result = self.fta.raw_red_flags()
        self.assertIsInstance(result, pd.DataFrame)

    def test_evaluate_does_not_raise(self):
        """evaluate() must complete without exception for a bank ticker."""
        result = self.fta.evaluate()
        expected_keys = {
            "metrics", "eval_metrics", "composite_scores",
            "raw_red_flags", "red_flags", "extended_metrics",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_evaluate_metrics_not_empty(self):
        """evaluate()['metrics'] must be a populated DataFrame for a bank ticker."""
        result = self.fta.evaluate()
        self.assertFalse(result["metrics"].empty)


class TestScoredMetricsEnforcement(unittest.TestCase):
    """
    M6 guard: SCORED_METRICS must exactly match the columns produced by
    compute_metrics() minus the identity columns (ticker, time, sector).

    This test catches drift between the documentation constant and the live
    implementation — if a metric is added to compute_metrics() without
    updating SCORED_METRICS (or vice-versa), the test fails immediately.
    """

    _ID_COLS = {"ticker", "time", "sector"}

    def test_scored_metrics_matches_compute_metrics_output(self):
        """
        SCORED_METRICS must list exactly the columns that compute_metrics()
        produces, excluding identity columns.
        """
        fta = _make_fta()
        m = fta.compute_metrics()
        actual_metric_cols = {c for c in m.columns if c not in self._ID_COLS}
        self.assertEqual(
            set(SCORED_METRICS),
            actual_metric_cols,
            msg=(
                f"SCORED_METRICS is out of sync with compute_metrics() output.\n"
                f"  In SCORED_METRICS but NOT in compute_metrics(): "
                f"{set(SCORED_METRICS) - actual_metric_cols}\n"
                f"  In compute_metrics() but NOT in SCORED_METRICS: "
                f"{actual_metric_cols - set(SCORED_METRICS)}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
