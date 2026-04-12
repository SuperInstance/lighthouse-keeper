"""Tests for challenge_suite.py and agent_client.py KeeperClient."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestChallengeFunctions:
    """Tests for individual challenge generators."""

    def test_cross_review_returns_tuple(self):
        from challenge_suite import challenge_cross_review
        cid, text, scoring = challenge_cross_review()
        assert cid == "CROSS-REVIEW-001"
        assert "Cross-Vessel Code Review" in text
        assert "Surplus Insight" in scoring

    def test_dead_agent_recovery_returns_tuple(self):
        from challenge_suite import challenge_dead_agent_recovery
        cid, text, scoring = challenge_dead_agent_recovery()
        assert cid == "DEAD-AGENT-001"
        assert "Dead Agent Recovery" in text
        assert "Causal Chain" in scoring

    def test_pattern_mining_returns_tuple(self):
        from challenge_suite import challenge_pattern_mining
        cid, text, scoring = challenge_pattern_mining()
        assert cid == "PATTERN-MINE-001"
        assert "Pattern Mining" in text

    def test_synthesis_returns_tuple(self):
        from challenge_suite import challenge_synthesis
        cid, text, scoring = challenge_synthesis()
        assert cid == "SYNTHESIS-001"
        assert "Architectural Synthesis" in text

    def test_self_improvement_returns_tuple(self):
        from challenge_suite import challenge_self_improvement
        cid, text, scoring = challenge_self_improvement()
        assert cid == "SELF-IMPROVE-001"
        assert "Self-Improvement" in text

    def test_coordination_returns_tuple(self):
        from challenge_suite import challenge_coordination
        cid, text, scoring = challenge_coordination()
        assert cid == "COORDINATION-001"
        assert "Bottle Negotiation" in text

    def test_fishing_returns_tuple(self):
        from challenge_suite import challenge_fishing
        cid, text, scoring = challenge_fishing()
        assert cid == "FISHING-001"
        assert "Fishery" in text

    def test_all_challenges_have_scoring(self):
        """Every challenge must include scoring criteria."""
        from challenge_suite import (
            challenge_cross_review, challenge_dead_agent_recovery,
            challenge_pattern_mining, challenge_synthesis,
            challenge_self_improvement, challenge_coordination,
            challenge_fishing,
        )
        challenges = [
            challenge_cross_review(), challenge_dead_agent_recovery(),
            challenge_pattern_mining(), challenge_synthesis(),
            challenge_self_improvement(), challenge_coordination(),
            challenge_fishing(),
        ]
        for cid, text, scoring in challenges:
            assert len(scoring.strip()) > 10, f"{cid} has empty scoring"


class TestWriteChallenge:
    """Tests for write_challenge()."""

    def test_write_challenge_calls_gh_write(self):
        from challenge_suite import write_challenge
        with patch("challenge_suite.gh_write_file") as mock_write:
            write_challenge("test-vessel", "TEST-001", "challenge text", "scoring criteria")
            mock_write.assert_called_once()
            args = mock_write.call_args
            # Should write to for-fleet/challenge-TEST-001.json
            assert "challenge-TEST-001.json" in args[0][1]

    def test_write_challenge_constructs_envelope(self):
        from challenge_suite import write_challenge
        with patch("challenge_suite.gh_write_file") as mock_write:
            write_challenge("SuperInstance/test-vessel", "TEST-001", "text", "scoring", timeout_minutes=45)
            call_args = mock_write.call_args
            envelope_str = call_args[0][2]  # content parameter
            envelope = json.loads(envelope_str)
            assert envelope["type"] == "CHALLENGE"
            assert envelope["challenge_id"] == "TEST-001"
            assert envelope["timeout_minutes"] == 45
            assert envelope["challenge"] == "text"
            assert envelope["scoring"] == "scoring"


class TestAgentClient:
    """Tests for agent_client.py KeeperClient."""

    def test_client_init(self):
        from agent_client import KeeperClient
        client = KeeperClient("http://localhost:8900", "test-vessel")
        assert client.keeper_url == "http://localhost:8900"
        assert client.vessel_name == "test-vessel"
        assert client.secret is None
        assert client.energy == 0

    def test_client_strips_trailing_slash(self):
        from agent_client import KeeperClient
        client = KeeperClient("http://localhost:8900/", "v")
        assert client.keeper_url == "http://localhost:8900"

    def test_register_sets_secret(self):
        from agent_client import KeeperClient
        client = KeeperClient("http://localhost:8900", "v")
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {"secret": "abc123", "status": "registered"}
            result = client.register()
            assert client.secret == "abc123"
            assert result["status"] == "registered"

    def test_register_failure_no_secret(self):
        from agent_client import KeeperClient
        client = KeeperClient("http://localhost:8900", "v")
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {"error": "already exists"}
            result = client.register()
            assert client.secret is None

    def test_spend_energy_updates_energy(self):
        from agent_client import KeeperClient
        client = KeeperClient("http://localhost:8900", "v")
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {"ok": True, "remaining": 450}
            result = client.spend_energy(50)
            assert client.energy == 450

    def test_regenerate_updates_energy(self):
        from agent_client import KeeperClient
        client = KeeperClient("http://localhost:8900", "v")
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {"remaining": 550}
            result = client.regenerate(100)
            assert client.energy == 550

    def test_send_i2i(self):
        from agent_client import KeeperClient
        client = KeeperClient("http://localhost:8900", "v")
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {"delivered": True}
            result = client.send_i2i("target/repo", "DISCOVER", {"info": "test"})
            mock_req.assert_called_once_with("POST", "/i2i", {
                "target": "target/repo",
                "type": "DISCOVER",
                "payload": {"info": "test"},
                "confidence": 0.5,
            })

    def test_respond_health(self):
        from agent_client import KeeperClient
        client = KeeperClient("http://localhost:8900", "v")
        client.energy = 800
        with patch.object(client, "write_file") as mock_write:
            mock_write.return_value = {"ok": True}
            result = client.respond_health("owner/repo", "still alive")
            mock_write.assert_called_once()
            args = mock_write.call_args
            assert "STATUS.json" in args[0][1]
            content = args[0][2]
            assert "still alive" in content
            assert '"energy": 800' in content

    def test_health_check(self):
        from agent_client import KeeperClient
        client = KeeperClient("http://localhost:8900", "v")
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {"status": "ok", "version": "2.1"}
            result = client.health()
            mock_req.assert_called_with("GET", "/health")
