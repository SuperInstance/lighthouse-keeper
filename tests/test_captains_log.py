"""Tests for captains_log_pipeline.py."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGetVoice:
    """Tests for get_voice()."""

    def test_known_vessel(self):
        from captains_log_pipeline import get_voice
        assert get_voice("oracle1-vessel") == "research/oracle"
        assert get_voice("JetsonClaw1-vessel") == "hardware/edge"
        assert get_voice("superz-vessel") == "build/coordination"

    def test_unknown_vessel_defaults(self):
        from captains_log_pipeline import get_voice
        assert get_voice("unknown-vessel") == "build/coordination"


class TestShouldSkip:
    """Tests for should_skip() — the 5-gate filter."""

    def test_skip_normal_text(self):
        from captains_log_pipeline import should_skip
        assert should_skip("I did some work today and it went fine") is True

    def test_pass_violated(self):
        from captains_log_pipeline import should_skip
        assert should_skip("The protocol was VIOLATED during the test") is False

    def test_pass_deviated(self):
        from captains_log_pipeline import should_skip
        assert should_skip("The agent DEVIATED from the expected path") is False

    def test_pass_pattern_nobody(self):
        from captains_log_pipeline import should_skip
        assert should_skip("A pattern emerged that nobody had reported") is False

    def test_pass_failed_unexplained(self):
        from captains_log_pipeline import should_skip
        assert should_skip("The test FAILED and we don't know why") is False

    def test_pass_killed(self):
        from captains_log_pipeline import should_skip
        assert should_skip("The process was KILLED by the system") is False

    def test_pass_prevented(self):
        from captains_log_pipeline import should_skip
        assert should_skip("The action was PREVENTED by the guard") is False

    def test_pass_fleet_insight(self):
        from captains_log_pipeline import should_skip
        assert should_skip("The fleet discovered a new insight about agents") is False

    def test_pass_systemic(self):
        from captains_log_pipeline import should_skip
        assert should_skip("This is a systemic issue with the fleet") is False

    def test_pass_rolled_back(self):
        from captains_log_pipeline import should_skip
        assert should_skip("The change was rolled back") is False


class TestPhase2Score:
    """Tests for phase2_score() parsing."""

    def test_skip_on_low_score(self):
        from captains_log_pipeline import phase2_score, RUBRIC
        with patch("captains_log_pipeline.call_zai") as mock_zai:
            mock_zai.return_value = (
                "Surplus Insight: 2\n"
                "Causal Chain: 3\n"
                "Honesty: 2\n"
                "Actionable Signal: 1\n"
                "Compression: 4\n"
                "Human Compatibility: 2\n"
                "Precedent Value: 3\n"
                "Average: 2.4\n"
                "SKIP"
            )
            signal, scores, avg = phase2_score("some raw text", "build/coordination")
            assert signal == "SKIP"

    def test_pass_on_high_score(self):
        from captains_log_pipeline import phase2_score
        with patch("captains_log_pipeline.call_zai") as mock_zai:
            mock_zai.return_value = (
                "Surplus Insight: 8\n"
                "Causal Chain: 7\n"
                "Honesty: 6\n"
                "Actionable Signal: 7\n"
                "Compression: 8\n"
                "Human Compatibility: 7\n"
                "Precedent Value: 6\n"
                "Average: 7.0\n"
                "The curated signal is that agents learn patterns from logs."
            )
            signal, scores, avg = phase2_score("some raw text", "research/oracle")
            assert signal != "SKIP"
            assert "curated signal" in signal
            assert avg >= 5.0


class TestRunLogPipeline:
    """Tests for run_log_pipeline()."""

    def test_empty_diary_returns_none(self):
        from captains_log_pipeline import run_log_pipeline
        result = run_log_pipeline("test-vessel", [])
        assert result is None

    def test_null_dump_returns_none(self):
        from captains_log_pipeline import run_log_pipeline
        with patch("captains_log_pipeline.phase1_raw_dump") as mock_raw, \
             patch("captains_log_pipeline.phase2_score") as mock_score:
            mock_raw.return_value = "NULL"
            result = run_log_pipeline("test-vessel", ["entry1"])
            assert result is None

    def test_skip_signal_returns_none(self):
        from captains_log_pipeline import run_log_pipeline
        with patch("captains_log_pipeline.phase1_raw_dump") as mock_raw, \
             patch("captains_log_pipeline.phase2_score") as mock_score:
            mock_raw.return_value = "Some interesting observation"
            mock_score.return_value = ("SKIP", {}, 3.0)
            result = run_log_pipeline("test-vessel", ["entry1"])
            assert result is None

    def test_full_pipeline_success(self):
        from captains_log_pipeline import run_log_pipeline
        with patch("captains_log_pipeline.phase1_raw_dump") as mock_raw, \
             patch("captains_log_pipeline.phase2_score") as mock_score, \
             patch("captains_log_pipeline.phase3_write") as mock_write:
            mock_raw.return_value = "Interesting observation about the code"
            mock_score.return_value = ("Signal extracted", {"Surplus Insight": 7}, 7.0)
            mock_write.return_value = "## Captain's Log\n\nSignal extracted..."
            result = run_log_pipeline("test-vessel", ["entry1", "entry2"])
            assert result is not None
            assert result["vessel"] == "test-vessel"
            assert result["vessel_type"] == "build/coordination"
            assert result["rubric_average"] == 7.0
            assert result["diary_entries_count"] == 2


class TestPatternLibrary:
    """Tests for PatternLibrary from agent_learning.py."""

    def test_add_and_get_patterns(self, tmp_path):
        from agent_learning import PatternLibrary
        lib = PatternLibrary(path=str(tmp_path / "patterns.json"))
        patterns = [
            {"name": "source-first debugging", "trigger": "bug found", "steps": ["read source"], "template_phrase": "Read the source first"},
            {"name": "cost-awareness", "trigger": "API call", "steps": ["count tokens"], "template_phrase": "Count the cost"},
        ]
        lib.add_patterns("debug/analysis", patterns)
        retrieved = lib.get_patterns("debug/analysis")
        assert len(retrieved) == 2
        assert retrieved[0]["name"] == "source-first debugging"

    def test_get_patterns_empty(self, tmp_path):
        from agent_learning import PatternLibrary
        lib = PatternLibrary(path=str(tmp_path / "patterns.json"))
        assert lib.get_patterns("nonexistent") == []

    def test_add_patterns_multiple_types(self, tmp_path):
        from agent_learning import PatternLibrary
        lib = PatternLibrary(path=str(tmp_path / "patterns.json"))
        lib.add_patterns("type-a", [{"name": "p1", "trigger": "t", "steps": [], "template_phrase": "tp"}])
        lib.add_patterns("type-b", [{"name": "p2", "trigger": "t", "steps": [], "template_phrase": "tp"}])
        all_patterns = lib.get_all_patterns()
        assert "type-a" in all_patterns["patterns"]
        assert "type-b" in all_patterns["patterns"]

    def test_pattern_library_persists(self, tmp_path):
        from agent_learning import PatternLibrary
        path = str(tmp_path / "patterns.json")
        lib1 = PatternLibrary(path=path)
        lib1.add_patterns("test", [{"name": "p", "trigger": "t", "steps": [], "template_phrase": "tp"}])
        lib2 = PatternLibrary(path=path)
        assert len(lib2.get_patterns("test")) == 1


class TestExtractThinkingPatterns:
    """Tests for extract_thinking_patterns()."""

    def test_valid_json_response(self):
        from agent_learning import extract_thinking_patterns
        fake_patterns = [{"name": "test", "trigger": "t", "steps": [], "template_phrase": "tp"}]
        with patch("agent_learning.call_zai") as mock:
            mock.return_value = json.dumps(fake_patterns)
            result = extract_thinking_patterns(["log1", "log2"])
            assert result["analyzed_count"] == 2
            assert len(result["patterns"]) == 1

    def test_invalid_json_falls_back(self):
        from agent_learning import extract_thinking_patterns
        with patch("agent_learning.call_zai") as mock:
            mock.return_value = "Not JSON at all"
            result = extract_thinking_patterns(["log1"])
            assert result["analyzed_count"] == 1
            assert result["patterns"] == []
            assert "raw_analysis" in result

    def test_json_in_code_block(self):
        from agent_learning import extract_thinking_patterns
        fake_patterns = [{"name": "test", "trigger": "t", "steps": [], "template_phrase": "tp"}]
        with patch("agent_learning.call_zai") as mock:
            mock.return_value = f"```json\n{json.dumps(fake_patterns)}\n```"
            result = extract_thinking_patterns(["log1"])
            assert len(result["patterns"]) == 1
