"""
Unit tests for config.py — sector weight dictionaries.

Covered:
  1. sector_metric_weights is deleted — not importable (P2-5 regression guard)
  2. sec_sector_metric_weights contains a "default" fallback key
  3. Every entry in sec_sector_metric_weights has the same metric key set
  4. No metric weight is negative
"""

import unittest
import financialtools.config as config


class TestLegacyDictRemoved(unittest.TestCase):
    """P2-5 regression: sector_metric_weights must not exist in config."""

    def test_sector_metric_weights_not_present(self):
        self.assertFalse(
            hasattr(config, "sector_metric_weights"),
            "sector_metric_weights was re-added to config — it must stay deleted. "
            "Use sec_sector_metric_weights (lowercase-dash keys) instead.",
        )


class TestSecSectorMetricWeights(unittest.TestCase):

    def setUp(self):
        self.weights = config.sec_sector_metric_weights

    def test_default_key_present(self):
        self.assertIn("default", self.weights, "sec_sector_metric_weights must have a 'default' key")

    def test_all_entries_have_same_metric_keys(self):
        """Every sector entry must expose the same set of metric keys."""
        reference_keys = set(self.weights["default"].keys())
        for sector, entry in self.weights.items():
            self.assertEqual(
                set(entry.keys()), reference_keys,
                f"Sector '{sector}' has different metric keys than 'default'",
            )

    def test_no_negative_weights(self):
        for sector, entry in self.weights.items():
            for metric, weight in entry.items():
                self.assertGreaterEqual(
                    weight, 0,
                    f"Negative weight {weight} for metric '{metric}' in sector '{sector}'",
                )

    def test_known_sectors_present(self):
        expected = {"technology", "financial-services", "healthcare", "energy", "utilities"}
        for sector in expected:
            self.assertIn(sector, self.weights, f"Expected sector '{sector}' not found")


if __name__ == "__main__":
    unittest.main()
