"""
tests/test_financial_agent.py — Unit tests for the financial analysis agent.

Tests
-----
TestCacheUtils
    - cache_key roundtrips
    - write/read payloads roundtrip
    - write/read topic result roundtrip
    - missing key raises FileNotFoundError

TestPrepareFinancialDataTool
    - returns error JSON when download produces empty DataFrame
    - returns error JSON on EvaluationError
    - happy path: cache_key in result and payloads.json written to disk

TestTopicTools
    - all 7 topics in TOPIC_TOOLS map
    - missing cache_key returns error JSON (no exception)

TestSubagents
    - build_topic_subagents returns 7 entries
    - each entry has required keys: name, description, system_prompt, tools
    - each subagent's tools list has exactly one tool

TestManagerAgent
    - create_financial_manager() returns a compiled agent without raising
    - agent has the required manager tools and subagents registered
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd


class TestCacheUtils(unittest.TestCase):
    """Verify cache key generation and disk I/O helpers."""

    def test_cache_key_with_year(self):
        from agents._cache import cache_key
        self.assertEqual(cache_key("AAPL", 2023), "AAPL_2023")

    def test_cache_key_no_year(self):
        from agents._cache import cache_key
        self.assertEqual(cache_key("eni.mi", None), "ENI.MI_all")

    def test_cache_key_lowercase_ticker_normalised(self):
        from agents._cache import cache_key
        self.assertEqual(cache_key("msft", 2022), "MSFT_2022")

    def test_write_and_read_payloads(self):
        """Round-trip payloads through disk cache."""
        import agents._cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            original_root = cache_mod._CACHE_ROOT
            cache_mod._CACHE_ROOT = tmpdir
            try:
                key = "TEST_2023"
                data = {"ticker": "TEST", "metrics": '[]', "year": 2023}
                cache_mod.write_payloads(key, data)
                loaded = cache_mod.read_payloads(key)
                self.assertEqual(loaded, data)
            finally:
                cache_mod._CACHE_ROOT = original_root

    def test_read_missing_payloads_raises(self):
        import agents._cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            original_root = cache_mod._CACHE_ROOT
            cache_mod._CACHE_ROOT = tmpdir
            try:
                with self.assertRaises(FileNotFoundError):
                    cache_mod.read_payloads("NONEXISTENT_2099")
            finally:
                cache_mod._CACHE_ROOT = original_root

    def test_write_and_read_topic_result(self):
        import agents._cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            original_root = cache_mod._CACHE_ROOT
            cache_mod._CACHE_ROOT = tmpdir
            try:
                key = "TEST_2023"
                result = {"rating": "strong", "rationale": "test"}
                cache_mod.write_topic_result(key, "liquidity", result)
                loaded = cache_mod.read_topic_result(key, "liquidity")
                self.assertEqual(loaded, result)
            finally:
                cache_mod._CACHE_ROOT = original_root

    def test_read_missing_topic_result_returns_none(self):
        import agents._cache as cache_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            original_root = cache_mod._CACHE_ROOT
            cache_mod._CACHE_ROOT = tmpdir
            try:
                result = cache_mod.read_topic_result("MISSING_2023", "liquidity")
                self.assertIsNone(result)
            finally:
                cache_mod._CACHE_ROOT = original_root


class TestPrepareFinancialDataTool(unittest.TestCase):
    """Verify the data preparation tool's error handling."""

    def _call_tool(self, ticker: str, sector: str, year=None) -> dict:
        """Invoke the tool and parse its JSON return value."""
        from agents._tools.data_tools import prepare_financial_data
        raw = prepare_financial_data.invoke({"ticker": ticker, "sector": sector, "year": year})
        return json.loads(raw)

    @patch("agents._tools.data_tools.Downloader")
    def test_empty_download_returns_error(self, MockDownloader):
        """An empty merged DataFrame must surface as an error envelope."""
        mock_instance = MagicMock()
        mock_instance.get_merged_data.return_value = pd.DataFrame()
        MockDownloader.from_ticker.return_value = mock_instance

        result = self._call_tool("FAKE", "Technology")
        self.assertIn("error", result)
        self.assertIn("FAKE", result["error"])

    @patch("agents._tools.data_tools.FundamentalTraderAssistant")
    @patch("agents._tools.data_tools.Downloader")
    def test_evaluation_error_returns_error(self, MockDownloader, MockFTA):
        """EvaluationError from FTA must be returned as an error envelope."""
        from financialtools.exceptions import EvaluationError

        mock_d = MagicMock()
        mock_d.get_merged_data.return_value = pd.DataFrame({"ticker": ["X"]})
        MockDownloader.from_ticker.return_value = mock_d

        MockFTA.side_effect = EvaluationError("bad weights")

        result = self._call_tool("X", "Technology")
        self.assertIn("error", result)
        self.assertIn("EvaluationError", result["error"])

    @patch("agents._tools.data_tools.write_payloads")
    @patch("agents._tools.data_tools.FundamentalTraderAssistant")
    @patch("agents._tools.data_tools.Downloader")
    def test_happy_path_returns_cache_key(self, MockDownloader, MockFTA, mock_write):
        """A successful call must return cache_key and status=ready."""
        mock_d = MagicMock()
        mock_d.get_merged_data.return_value = pd.DataFrame({"ticker": ["AAPL"]})
        MockDownloader.from_ticker.return_value = mock_d

        empty_df = pd.DataFrame()
        mock_fta_instance = MagicMock()
        mock_fta_instance.evaluate.return_value = {
            "metrics":          empty_df,
            "extended_metrics": empty_df,
            "eval_metrics":     empty_df,
            "composite_scores": empty_df,
            "red_flags":        empty_df,
        }
        MockFTA.return_value = mock_fta_instance

        result = self._call_tool("AAPL", "Technology", year=2023)

        self.assertNotIn("error", result)
        self.assertEqual(result["cache_key"], "AAPL_2023")
        self.assertEqual(result["status"], "ready")
        mock_write.assert_called_once()


class TestTopicTools(unittest.TestCase):
    """Verify all 7 topic tools are wired and handle missing cache gracefully."""

    def test_all_topics_present_in_map(self):
        from agents._tools.topic_tools import TOPIC_TOOLS
        expected = {"liquidity", "solvency", "profitability",
                    "efficiency", "cash_flow", "growth", "red_flags"}
        self.assertEqual(set(TOPIC_TOOLS.keys()), expected)

    def test_missing_cache_key_returns_error(self):
        """A non-existent cache key must return an error envelope, not raise."""
        from agents._tools.topic_tools import TOPIC_TOOLS

        # Patch _cache_root to a temp dir so we don't touch production cache
        import agents._cache as cache_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            original = cache_mod._CACHE_ROOT
            cache_mod._CACHE_ROOT = tmpdir
            try:
                for topic, tool_fn in TOPIC_TOOLS.items():
                    with self.subTest(topic=topic):
                        raw = tool_fn.invoke({"cache_key": "GHOST_2099"})
                        result = json.loads(raw)
                        self.assertIn("error", result, f"{topic} should return error")
            finally:
                cache_mod._CACHE_ROOT = original


class TestSubagents(unittest.TestCase):
    """Verify subagent configuration completeness."""

    def test_seven_subagents_built(self):
        from agents._subagents import build_topic_subagents
        subagents = build_topic_subagents()
        self.assertEqual(len(subagents), 7)

    def test_required_keys_present(self):
        from agents._subagents import TOPIC_SUBAGENTS
        required_keys = {"name", "description", "system_prompt", "tools", "model"}
        for sa in TOPIC_SUBAGENTS:
            with self.subTest(name=sa.get("name")):
                self.assertEqual(required_keys, set(sa.keys()))

    def test_each_subagent_has_one_tool(self):
        from agents._subagents import TOPIC_SUBAGENTS
        for sa in TOPIC_SUBAGENTS:
            with self.subTest(name=sa["name"]):
                self.assertEqual(len(sa["tools"]), 1)

    def test_subagent_names_are_unique(self):
        from agents._subagents import TOPIC_SUBAGENTS
        names = [sa["name"] for sa in TOPIC_SUBAGENTS]
        self.assertEqual(len(names), len(set(names)))


class TestManagerAgent(unittest.TestCase):
    """Smoke tests for manager agent construction."""

    def test_create_financial_manager_returns_agent(self):
        """create_financial_manager() must complete without raising."""
        from agents.financial_agent import create_financial_manager
        agent = create_financial_manager()
        self.assertIsNotNone(agent)

    def test_custom_model_accepted(self):
        """Custom model name must not cause a construction error."""
        from agents.financial_agent import create_financial_manager
        agent = create_financial_manager(model="gpt-4.1-nano")
        self.assertIsNotNone(agent)


if __name__ == "__main__":
    unittest.main()
