"""Tests for HealthMonitor (from keeper.py)."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime, timezone, timedelta

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def components(tmp_path):
    """Create HealthMonitor with mocked dependencies."""
    from keeper import HealthMonitor, AgentRegistry, GitHub

    fleet_file = str(tmp_path / "fleet_state.json")
    agents_file = str(tmp_path / "agents.json")
    audit_file = str(tmp_path / "audit.log")
    baton_file = str(tmp_path / "baton_registry.json")

    gh = MagicMock(spec=GitHub)
    gh.last_commit_age = MagicMock(return_value=100)
    gh.discover_vessels = MagicMock(return_value=[])
    gh.read_file = MagicMock(return_value=None)
    gh.write_file = MagicMock(return_value={})
    gh.post = MagicMock(return_value={})

    registry = AgentRegistry.__new__(AgentRegistry)
    registry.agents = {}
    registry._lock = MagicMock()
    registry._save = MagicMock()

    monitor = HealthMonitor.__new__(HealthMonitor)
    monitor.gh = gh
    monitor.registry = registry
    monitor.fleet_state = {"vessels": {}}
    monitor._check_index = 0
    monitor._running = False

    # Patch save_json to write to temp
    def fake_save(path, data):
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    with patch("keeper.save_json", side_effect=fake_save), \
         patch("keeper.FLEET_STATE_FILE", fleet_file):
        pass  # patches applied at module level

    # We'll manually call save_json when needed
    return monitor, gh, registry, fleet_file


class TestHealthMonitorCheckOne:
    """Tests for HealthMonitor.check_one()."""

    def test_active_status_for_recent_commit(self, components):
        monitor, gh, _, fleet_file = components
        gh.last_commit_age.return_value = 120  # 2 minutes

        def fake_save(path, data):
            monitor.fleet_state = data
        with patch("keeper.save_json", side_effect=fake_save):
            state = monitor.check_one("owner/repo")
        assert state["status"] == "active"
        assert state["missed"] == 0

    def test_idle_status(self, components):
        monitor, gh, _, fleet_file = components
        gh.last_commit_age.return_value = 600

        def fake_save(path, data):
            monitor.fleet_state = data
        with patch("keeper.save_json", side_effect=fake_save):
            state = monitor.check_one("owner/repo")
        assert state["status"] == "idle"
        assert state["missed"] == 1

    def test_stale_status(self, components):
        monitor, gh, _, fleet_file = components
        gh.last_commit_age.return_value = 36000

        def fake_save(path, data):
            monitor.fleet_state = data
        with patch("keeper.save_json", side_effect=fake_save):
            state = monitor.check_one("owner/repo")
        assert state["status"] == "stale"
        assert state["missed"] == 1

    def test_dead_status(self, components):
        monitor, gh, _, fleet_file = components
        gh.last_commit_age.return_value = 200000

        def fake_save(path, data):
            monitor.fleet_state = data
        with patch("keeper.save_json", side_effect=fake_save):
            state = monitor.check_one("owner/repo")
        assert state["status"] == "dead"
        assert state["missed"] == 1

    def test_unknown_status_when_api_fails(self, components):
        monitor, gh, _, fleet_file = components
        gh.last_commit_age.return_value = None

        def fake_save(path, data):
            monitor.fleet_state = data
        with patch("keeper.save_json", side_effect=fake_save):
            state = monitor.check_one("owner/repo")
        assert state["status"] == "unknown"
        assert state["missed"] == 1

    def test_missed_increments_on_stale(self, components):
        monitor, gh, _, fleet_file = components
        gh.last_commit_age.return_value = 36000

        def fake_save(path, data):
            monitor.fleet_state = data
        with patch("keeper.save_json", side_effect=fake_save):
            monitor.check_one("owner/repo")
            state2 = monitor.check_one("owner/repo")
        assert state2["missed"] == 2

    def test_missed_resets_on_active(self, components):
        monitor, gh, _, fleet_file = components

        def fake_save(path, data):
            monitor.fleet_state = data

        # First: stale
        gh.last_commit_age.return_value = 36000
        with patch("keeper.save_json", side_effect=fake_save):
            monitor.check_one("owner/repo")
        # Then: active
        gh.last_commit_age.return_value = 60
        with patch("keeper.save_json", side_effect=fake_save):
            state = monitor.check_one("owner/repo")
        assert state["missed"] == 0
        assert state["status"] == "active"


class TestHealthMonitorIntervention:
    """Tests for intervention thresholds."""

    def test_alert_threshold(self, components):
        monitor, gh, _, fleet_file = components
        from keeper import MISSED_BEFORE_ALERT
        gh.last_commit_age.return_value = 36000

        def fake_save(path, data):
            monitor.fleet_state = data
        with patch("keeper.save_json", side_effect=fake_save):
            for _ in range(MISSED_BEFORE_ALERT):
                state = monitor.check_one("owner/repo")
        assert state["intervention"] == "alert"

    def test_reboot_threshold(self, components):
        monitor, gh, _, fleet_file = components
        from keeper import MISSED_BEFORE_REBOOT
        gh.last_commit_age.return_value = 36000

        def fake_save(path, data):
            monitor.fleet_state = data
        with patch("keeper.save_json", side_effect=fake_save):
            for _ in range(MISSED_BEFORE_REBOOT):
                state = monitor.check_one("owner/repo")
        assert state["intervention"] == "reboot"


class TestHealthMonitorTick:
    """Tests for HealthMonitor.tick()."""

    def test_tick_checks_agents_per_tick(self, components):
        monitor, gh, _, fleet_file = components
        from keeper import AGENTS_PER_TICK
        gh.last_commit_age.return_value = 100

        monitor.fleet_state["vessels"] = {
            f"owner/repo{i}": {} for i in range(10)
        }

        def fake_save(path, data):
            monitor.fleet_state = data

        with patch("keeper.save_json", side_effect=fake_save):
            checked = monitor.tick()
        assert len(checked) == AGENTS_PER_TICK

    def test_tick_empty_fleet(self, components):
        monitor, gh, _, fleet_file = components
        result = monitor.tick()
        assert result is None


class TestHealthMonitorStop:
    """Tests for HealthMonitor.stop()."""

    def test_stop(self, components):
        monitor, _, _, _ = components
        monitor._running = True
        monitor.stop()
        assert monitor._running is False


class TestHealthMonitorVesselList:
    """Tests for vessel list construction."""

    def test_vessel_list_includes_registered(self, components):
        monitor, _, registry, _ = components
        registry.agents = {"v1": {}, "v2": {}}
        vessels = monitor._vessel_list()
        assert "v1" in vessels
        assert "v2" in vessels

    def test_vessel_list_deduplicates(self, components):
        monitor, _, registry, _ = components
        registry.agents = {"v1": {}}
        monitor.fleet_state["vessels"] = {"v1": {}, "v2": {}}
        vessels = monitor._vessel_list()
        assert len([v for v in vessels if v == "v1"]) == 1
