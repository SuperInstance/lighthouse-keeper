"""Tests for lighthouse-keeper utility functions."""

import json
import os
import tempfile
import pytest
from unittest.mock import patch
from datetime import datetime, timezone

# ── Import utilities from keeper.py ──

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAudit:
    """Tests for the audit() utility."""

    def test_audit_creates_log_file(self, tmp_path):
        """audit() should append a timestamped line to the audit log."""
        from keeper import audit, AUDIT_LOG
        with patch("keeper.AUDIT_LOG", str(tmp_path / "audit.log")):
            audit("test event happened")
        content = (tmp_path / "audit.log").read_text()
        assert "test event happened" in content
        assert "[" in content  # timestamp prefix

    def test_audit_appends_multiple_entries(self, tmp_path):
        """Multiple audit calls should all appear in the log."""
        from keeper import audit
        log_file = str(tmp_path / "audit.log")
        with patch("keeper.AUDIT_LOG", log_file):
            audit("first")
            audit("second")
            audit("third")
        lines = open(log_file).readlines()
        assert len(lines) == 3


class TestTsNow:
    """Tests for ts_now()."""

    def test_ts_now_returns_iso_format(self):
        from keeper import ts_now
        result = ts_now()
        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None  # should be timezone-aware


class TestLoadJson:
    """Tests for load_json()."""

    def test_load_existing_json(self, tmp_path):
        from keeper import load_json
        f = tmp_path / "test.json"
        f.write_text('{"a": 1}')
        result = load_json(str(f))
        assert result == {"a": 1}

    def test_load_missing_file_returns_default(self, tmp_path):
        from keeper import load_json
        result = load_json(str(tmp_path / "nonexistent.json"), default={"x": 42})
        assert result == {"x": 42}

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        from keeper import load_json
        result = load_json(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_load_corrupt_json_returns_default(self, tmp_path):
        from keeper import load_json
        f = tmp_path / "bad.json"
        f.write_text("not json at all")
        result = load_json(str(f), default="fallback")
        assert result == "fallback"


class TestSaveJson:
    """Tests for save_json()."""

    def test_save_json_writes_file(self, tmp_path):
        from keeper import save_json
        f = str(tmp_path / "out.json")
        save_json(f, {"key": "value"})
        assert json.loads(open(f).read()) == {"key": "value"}

    def test_save_json_handles_datetime(self, tmp_path):
        from keeper import save_json
        f = str(tmp_path / "out.json")
        now = datetime.now(timezone.utc)
        save_json(f, {"ts": now})
        data = json.loads(open(f).read())
        assert "ts" in data
