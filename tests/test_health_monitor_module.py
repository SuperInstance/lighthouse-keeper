"""Tests for health_monitor.py (FleetHealthMonitor)."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFleetHealthMonitorInit:
    """Tests for FleetHealthMonitor initialization."""

    def test_init(self):
        from health_monitor import FleetHealthMonitor
        with patch("health_monitor.GITHUB_TOKEN", "fake"):
            mon = FleetHealthMonitor()
        assert mon.agent_health == {}
        assert mon.audit_log == []


class TestFleetHealthMonitorCheckAgentHealth:
    """Tests for check_agent_health()."""

    @pytest.fixture
    def monitor(self):
        from health_monitor import FleetHealthMonitor
        with patch("health_monitor.GITHUB_TOKEN", "fake"):
            mon = FleetHealthMonitor()
        return mon

    def test_active_agent(self, monitor):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
        monitor._api_get = MagicMock(return_value=[{
            "commit": {"author": {"date": recent}}
        }])
        health = monitor.check_agent_health("owner/repo")
        assert health["status"] == "active"
        assert health["missed_cycles"] == 0

    def test_idle_agent(self, monitor):
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(seconds=2000)).isoformat()
        monitor._api_get = MagicMock(return_value=[{
            "commit": {"author": {"date": past}}
        }])
        health = monitor.check_agent_health("owner/repo")
        assert health["status"] == "idle"

    def test_stale_agent(self, monitor):
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        monitor._api_get = MagicMock(return_value=[{
            "commit": {"author": {"date": past}}
        }])
        health = monitor.check_agent_health("owner/repo")
        assert health["status"] == "stale"

    def test_dead_agent(self, monitor):
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        monitor._api_get = MagicMock(return_value=[{
            "commit": {"author": {"date": past}}
        }])
        health = monitor.check_agent_health("owner/repo")
        assert health["status"] == "dead"

    def test_unknown_agent_no_commits(self, monitor):
        monitor._api_get = MagicMock(return_value=None)
        health = monitor.check_agent_health("owner/repo")
        assert health["status"] == "unknown"
        assert health["last_commit_age"] is None

    def test_has_status_json(self, monitor):
        import base64
        status_data = {"energy_remaining": 800, "confidence": 0.7}
        status_json = json.dumps(status_data)
        encoded = base64.b64encode(status_json.encode()).decode()

        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()

        monitor._api_get = MagicMock(side_effect=[
            [{"commit": {"author": {"date": recent}}}],  # commits
            {"content": encoded},  # STATUS.json
        ])
        health = monitor.check_agent_health("owner/repo")
        assert health["has_status"] is True
        assert health["energy"] == 800
        assert health["confidence"] == 0.7

    def test_has_diary(self, monitor):
        import base64
        diary = "# Diary\nSome entry about work done today\nAnother line"
        encoded = base64.b64encode(diary.encode()).decode()

        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()

        monitor._api_get = MagicMock(side_effect=[
            [{"commit": {"author": {"date": recent}}}],
            None,  # STATUS.json
            {"content": encoded},  # DIARY
            None,  # BOOTCAMP.md
        ])
        health = monitor.check_agent_health("owner/repo")
        assert health["has_diary"] is True
        assert health["last_diary_entry"] is not None

    def test_has_bootcamp(self, monitor):
        import base64
        bootcamp = "x" * 100  # > 50 chars = has bootcamp
        encoded = base64.b64encode(bootcamp.encode()).decode()

        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()

        monitor._api_get = MagicMock(side_effect=[
            [{"commit": {"author": {"date": recent}}}],
            None, None,
            {"content": encoded},
        ])
        health = monitor.check_agent_health("owner/repo")
        assert health["has_bootcamp"] is True

    def test_missed_cycles_increment(self, monitor):
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        monitor._api_get = MagicMock(return_value=[{
            "commit": {"author": {"date": past}}
        }])
        monitor.check_agent_health("owner/repo")
        health2 = monitor.check_agent_health("owner/repo")
        assert health2["missed_cycles"] == 2

    def test_missed_cycles_reset_on_active(self, monitor):
        from datetime import datetime, timezone, timedelta
        # First: stale
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        monitor._api_get = MagicMock(return_value=[{
            "commit": {"author": {"date": past}}
        }])
        monitor.check_agent_health("owner/repo")
        # Then: active
        recent = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
        monitor._api_get = MagicMock(return_value=[{
            "commit": {"author": {"date": recent}}
        }])
        health = monitor.check_agent_health("owner/repo")
        assert health["missed_cycles"] == 0


class TestFleetHealthMonitorIntervention:
    """Tests for intervention levels."""

    def test_health_alert_threshold(self):
        from health_monitor import FleetHealthMonitor, MISSED_CYCLES_BEFORE_ALERT
        with patch("health_monitor.GITHUB_TOKEN", "fake"):
            mon = FleetHealthMonitor()
        mon.agent_health["owner/repo"] = {
            "status": "stale", "missed_cycles": MISSED_CYCLES_BEFORE_ALERT - 1
        }
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        mon._api_get = MagicMock(return_value=[{
            "commit": {"author": {"date": past}}
        }])
        health = mon.check_agent_health("owner/repo")
        assert health["intervention"] == "HEALTH_ALERT"

    def test_reboot_candidate_threshold(self):
        from health_monitor import FleetHealthMonitor, MISSED_CYCLES_BEFORE_REBOOT
        with patch("health_monitor.GITHUB_TOKEN", "fake"):
            mon = FleetHealthMonitor()
        mon.agent_health["owner/repo"] = {
            "status": "stale", "missed_cycles": MISSED_CYCLES_BEFORE_REBOOT - 1
        }
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        mon._api_get = MagicMock(return_value=[{
            "commit": {"author": {"date": past}}
        }])
        health = mon.check_agent_health("owner/repo")
        assert health["intervention"] == "REBOOT_CANDIDATE"


class TestFleetHealthMonitorDiscoverVessels:
    """Tests for discover_vessels()."""

    def test_discovers_vessels(self):
        from health_monitor import FleetHealthMonitor
        with patch("health_monitor.GITHUB_TOKEN", "fake"):
            mon = FleetHealthMonitor()
        repos = [
            {"name": "flux-runtime", "full_name": "Org/flux-runtime"},
            {"name": "other-repo", "full_name": "Org/other-repo"},
            {"name": "agent-vessel", "full_name": "Org/agent-vessel"},
        ]
        call_count = [0]
        def fake_api_get(path):
            call_count[0] += 1
            if call_count[0] == 1:
                return repos
            return []  # Stop pagination
        mon._api_get = fake_api_get
        vessels = mon.discover_vessels()
        assert len(vessels) == 2
