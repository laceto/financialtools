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

    def _call_tool(self, ticker: str, sector: str | None = None, year=None) -> dict:
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

    @patch("agents._tools.data_tools.FundamentalMetricsEvaluator")
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
    @patch("agents._tools.data_tools.FundamentalMetricsEvaluator")
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

    @patch("agents._tools.data_tools.write_payloads")
    @patch("agents._tools.data_tools.FundamentalMetricsEvaluator")
    @patch("agents._tools.data_tools.Downloader")
    def test_sector_auto_detected_from_info(self, MockDownloader, MockFTA, mock_write):
        """When sector=None, sector is read from get_info_data()['sector']."""
        mock_d = MagicMock()
        mock_d.get_merged_data.return_value = pd.DataFrame({"ticker": ["AAPL"]})
        mock_d.get_info_data.return_value = pd.DataFrame({"sector": ["Technology Services"]})
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

        result = self._call_tool("AAPL", sector=None)

        self.assertNotIn("error", result)
        self.assertEqual(result["sector"], "technology-services")

    @patch("agents._tools.data_tools.write_payloads")
    @patch("agents._tools.data_tools.FundamentalMetricsEvaluator")
    @patch("agents._tools.data_tools.Downloader")
    def test_sector_falls_back_to_default_when_info_missing(self, MockDownloader, MockFTA, mock_write):
        """When sector=None and info has no 'sector' column, sector defaults to 'Default'."""
        mock_d = MagicMock()
        mock_d.get_merged_data.return_value = pd.DataFrame({"ticker": ["AAPL"]})
        mock_d.get_info_data.return_value = pd.DataFrame()  # empty — no sector column
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

        result = self._call_tool("AAPL", sector=None)

        self.assertNotIn("error", result)
        self.assertEqual(result["sector"], "default")


class TestTopicTools(unittest.TestCase):
    """Verify all 7 topic tools are wired and handle missing cache gracefully."""

    def test_all_topics_present_in_map(self):
        from agents._tools.topic_tools import TOPIC_TOOLS
        expected = {"liquidity", "solvency", "profitability",
                    "efficiency", "cash_flow", "growth", "red_flags",
                    "quantitative_overview"}
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
    """Verify topic subgraph construction."""

    def test_seven_subgraphs_built(self):
        """build_topic_subgraphs() must return exactly 8 compiled graphs."""
        from agents._subagents import build_topic_subgraphs
        subgraphs = build_topic_subgraphs()
        self.assertEqual(len(subgraphs), 8)

    def test_subgraph_keys_match_topic_names(self):
        """Keys must exactly match TOPIC_NAMES."""
        from agents._subagents import TOPIC_NAMES, build_topic_subgraphs
        subgraphs = build_topic_subgraphs()
        self.assertEqual(set(subgraphs.keys()), set(TOPIC_NAMES))

    def test_each_subgraph_is_compiled(self):
        """Each value must be a compiled LangGraph (has .invoke)."""
        from agents._subagents import build_topic_subgraphs
        subgraphs = build_topic_subgraphs()
        for topic, sg in subgraphs.items():
            with self.subTest(topic=topic):
                self.assertTrue(callable(getattr(sg, "invoke", None)),
                                f"{topic} subgraph missing .invoke()")


class TestManagerAgent(unittest.TestCase):
    """Smoke tests for the LangGraph StateGraph manager."""

    def test_create_financial_manager_returns_agent(self):
        """create_financial_manager() must compile without raising."""
        from agents.financial_agent import create_financial_manager
        agent = create_financial_manager()
        self.assertIsNotNone(agent)

    def test_custom_model_accepted(self):
        """Custom model name must not cause a construction error."""
        from agents.financial_agent import create_financial_manager
        agent = create_financial_manager(model="gpt-4.1-nano")
        self.assertIsNotNone(agent)

    def test_agent_has_invoke(self):
        """Compiled graph must expose .invoke() and .stream()."""
        from agents.financial_agent import create_financial_manager
        agent = create_financial_manager()
        self.assertTrue(callable(getattr(agent, "invoke", None)))
        self.assertTrue(callable(getattr(agent, "stream", None)))

    def test_agent_graph_nodes_include_all_topics(self):
        """Compiled graph must contain a node for every topic analyst."""
        from agents._subagents import TOPIC_NAMES
        from agents.financial_agent import create_financial_manager
        agent = create_financial_manager()
        node_names = set(agent.get_graph().nodes.keys())
        for topic in TOPIC_NAMES:
            with self.subTest(topic=topic):
                self.assertIn(f"{topic}_analyst", node_names)


if __name__ == "__main__":
    unittest.main()
