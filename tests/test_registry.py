"""Tests for AgentRegistry."""

import json
import os
import time
import pytest
from unittest.mock import patch

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def registry(tmp_path):
    """Create a registry backed by a temp file."""
    agents_file = str(tmp_path / "agents.json")
    from keeper import AgentRegistry, save_json
    # Create the registry using __new__ to bypass __init__ reading AGENTS_FILE
    reg = AgentRegistry.__new__(AgentRegistry)
    reg.agents = {}
    reg._lock = type('Lock', (), {'__enter__': lambda s: None, '__exit__': lambda s, *a: None})()
    # Override _save to use temp path
    def fake_save():
        save_json(agents_file, reg.agents)
    reg._save = fake_save
    return reg


class TestAgentRegistryRegister:
    """Tests for AgentRegistry.register()."""

    def test_register_new_agent(self, registry):
        result = registry.register("test-vessel")
        assert result["status"] == "registered"
        assert result["agent_id"] == "test-vessel"
        assert "secret" in result
        assert len(result["secret"]) == 32
        assert "test-vessel" in registry.agents

    def test_register_returns_secret(self, registry):
        result = registry.register("v1")
        assert result["secret"]

    def test_register_already_registered(self, registry):
        r1 = registry.register("v1")
        r2 = registry.register("v1")
        assert r2["status"] == "already_registered"
        assert r2["secret"] == r1["secret"]

    def test_register_preserves_existing_agents(self, registry):
        registry.register("v1")
        registry.register("v2")
        assert len(registry.agents) == 2


class TestAgentRegistryVerify:
    """Tests for AgentRegistry.verify()."""

    def test_verify_correct_secret(self, registry):
        result = registry.register("v1")
        assert registry.verify("v1", result["secret"]) is True

    def test_verify_wrong_secret(self, registry):
        registry.register("v1")
        assert registry.verify("v1", "wrong-secret") is False

    def test_verify_unknown_agent(self, registry):
        # verify returns None for unknown agents (agent is None, and None and ... returns None)
        result = registry.verify("nonexistent", "any")
        assert result is not True  # None or False

    def test_verify_empty_secret(self, registry):
        registry.register("v1")
        assert registry.verify("v1", "") is False


class TestAgentRegistryTouch:
    """Tests for AgentRegistry.touch()."""

    def test_touch_updates_last_seen(self, registry):
        registry.register("v1")
        time.sleep(0.01)
        registry.touch("v1")
        assert "last_seen" in registry.agents["v1"]

    def test_touch_increments_requests(self, registry):
        registry.register("v1")
        registry.touch("v1")
        registry.touch("v1")
        assert registry.agents["v1"]["requests"] == 2

    def test_touch_unknown_agent_no_error(self, registry):
        registry.touch("nonexistent")  # should not raise


class TestAgentRegistryEnergy:
    """Tests for energy budgeting."""

    def test_spend_energy_success(self, registry):
        registry.register("v1")
        assert registry.spend_energy("v1", 100) is True
        # ENERGY_DEFAULT is 1000, minus 100
        assert registry.agents["v1"]["energy_remaining"] == 900

    def test_spend_energy_insufficient(self, registry):
        registry.register("v1")
        assert registry.spend_energy("v1", 9999) is False
        assert registry.agents["v1"]["energy_remaining"] == 1000

    def test_spend_energy_unknown_agent(self, registry):
        assert registry.spend_energy("nonexistent", 10) is False

    def test_regenerate_energy(self, registry):
        registry.register("v1")
        registry.spend_energy("v1", 200)
        registry.regenerate("v1", 100)
        assert registry.agents["v1"]["energy_remaining"] == 900

    def test_regenerate_caps_at_budget(self, registry):
        registry.register("v1")
        registry.regenerate("v1", 9999)
        assert registry.agents["v1"]["energy_remaining"] == 1000

    def test_regenerate_unknown_agent(self, registry):
        registry.regenerate("nonexistent", 100)  # should not raise


class TestAgentRegistryList:
    """Tests for AgentRegistry.list_agents()."""

    def test_list_empty(self, registry):
        assert registry.list_agents() == []

    def test_list_returns_all(self, registry):
        registry.register("v1")
        registry.register("v2")
        agents = registry.list_agents()
        assert len(agents) == 2
        for a in agents:
            assert "vessel" in a
            assert "last_seen" in a
            assert "energy" in a
            assert "requests" in a
