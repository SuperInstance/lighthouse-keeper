"""Tests for GitHub API wrapper."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGitHubInit:
    """Tests for GitHub class initialization."""

    def test_github_init_with_token(self):
        from keeper import GitHub
        gh = GitHub("test-token", "TestOrg")
        assert gh.token == "test-token"
        assert gh.org == "TestOrg"
        assert gh._call_count == 0
        assert gh._headers["Authorization"] == "token test-token"
        assert gh._headers["Content-Type"] == "application/json"

    def test_github_call_count_increments(self):
        from keeper import GitHub
        gh = GitHub("tok", "Org")
        assert gh._call_count == 0
        gh._call_count += 1
        assert gh._call_count == 1


class TestGitHubReadFile:
    """Tests for GitHub.read_file()."""

    def test_read_file_success(self):
        from keeper import GitHub
        import base64
        gh = GitHub("tok", "Org")
        content = "hello world"
        encoded = base64.b64encode(content.encode()).decode()
        gh.get = MagicMock(return_value={"content": encoded, "sha": "abc123"})
        result = gh.read_file("owner/repo", "path/file.txt")
        assert result == (content, "abc123")

    def test_read_file_api_error(self):
        from keeper import GitHub
        gh = GitHub("tok", "Org")
        gh.get = MagicMock(return_value={"_error": 404})
        result = gh.read_file("owner/repo", "missing.txt")
        assert result is None

    def test_read_file_no_content_key(self):
        from keeper import GitHub
        gh = GitHub("tok", "Org")
        gh.get = MagicMock(return_value={"message": "ok"})
        result = gh.read_file("owner/repo", "dir/")
        assert result == (None, None)


class TestGitHubLastCommitAge:
    """Tests for GitHub.last_commit_age()."""

    def test_last_commit_age_returns_seconds(self):
        from keeper import GitHub
        from datetime import datetime, timezone, timedelta
        gh = GitHub("tok", "Org")
        past = (datetime.now(timezone.utc) - timedelta(seconds=500))
        # Format as GitHub API returns: "2024-01-01T00:00:00Z"
        past_str = past.strftime("%Y-%m-%dT%H:%M:%SZ")
        gh.get = MagicMock(return_value=[{
            "commit": {"author": {"date": past_str}}
        }])
        age = gh.last_commit_age("owner/repo")
        assert age is not None
        assert 490 <= age <= 510  # allow for timing

    def test_last_commit_age_no_commits(self):
        from keeper import GitHub
        gh = GitHub("tok", "Org")
        gh.get = MagicMock(return_value=[])
        assert gh.last_commit_age("owner/repo") is None

    def test_last_commit_age_api_error(self):
        from keeper import GitHub
        gh = GitHub("tok", "Org")
        gh.get = MagicMock(return_value={"_error": 403})
        assert gh.last_commit_age("owner/repo") is None


class TestGitHubDiscoverVessels:
    """Tests for GitHub.discover_vessels()."""

    def test_discovers_vessels(self):
        from keeper import GitHub
        gh = GitHub("tok", "Org")
        repos = [
            {"name": "something-random", "full_name": "Org/something-random"},
            {"name": "flux-runtime", "full_name": "Org/flux-runtime"},
            {"name": "oracle1-vessel", "full_name": "Org/oracle1-vessel"},
        ]
        gh.get = MagicMock(return_value=repos)
        vessels = gh.discover_vessels()
        assert len(vessels) == 2
        assert "Org/flux-runtime" in vessels
        assert "Org/oracle1-vessel" in vessels

    def test_discovers_vessels_empty(self):
        from keeper import GitHub
        gh = GitHub("tok", "Org")
        gh.get = MagicMock(return_value=[])
        assert gh.discover_vessels() == []


class TestGitHubWriteFile:
    """Tests for GitHub.write_file()."""

    def test_write_file_without_sha(self):
        from keeper import GitHub
        gh = GitHub("tok", "Org")
        gh.put = MagicMock(return_value={"content": {"sha": "new123"}})
        result = gh.write_file("owner/repo", "test.md", "hello", "commit msg")
        gh.put.assert_called_once()
        call_args = gh.put.call_args
        assert "test.md" in call_args[0][0]
        body = call_args[0][1]
        assert body["message"] == "commit msg"
        assert "content" in body
        assert "sha" not in body

    def test_write_file_with_sha(self):
        from keeper import GitHub
        gh = GitHub("tok", "Org")
        gh.put = MagicMock(return_value={"content": {"sha": "new123"}})
        gh.write_file("owner/repo", "test.md", "hello", "msg", sha="old456")
        body = gh.put.call_args[0][1]
        assert body["sha"] == "old456"
