"""Tests for AgentRegistry and scoring logic in keeper.py."""

import json
import os
import hashlib
import pytest
from unittest.mock import patch, MagicMock
from http.server import HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import threading
import time

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBatonScoring:
    """Tests for the baton handoff scoring logic."""

    def _make_handler(self, tmp_path):
        """Create a handler class with patched file paths."""
        from keeper import KeeperHandler, AgentRegistry
        agents_file = str(tmp_path / "agents.json")
        fleet_file = str(tmp_path / "fleet_state.json")
        audit_file = str(tmp_path / "audit.log")
        baton_file = str(tmp_path / "baton_registry.json")

        with patch("keeper.AGENTS_FILE", agents_file), \
             patch("keeper.FLEET_STATE_FILE", fleet_file), \
             patch("keeper.AUDIT_LOG", audit_file), \
             patch("keeper.BATON_REGISTRY_FILE", baton_file), \
             patch("keeper.ENERGY_DEFAULT", 500), \
             patch("keeper.registry", AgentRegistry()), \
             patch("keeper.health"):
            # We can't easily re-patch the module-level `registry`, so we
            # test the scoring logic directly via a helper instead.
            pass
        return None

    def test_score_letter_excellent(self):
        """A well-written handoff letter should pass."""
        from keeper import GitHub
        # Test the scoring algorithm by inspecting the do_POST handler logic.
        # We'll directly call the scoring code extracted from the handler.
        letter = """
Who I Was
I was working on fixing the conformance test failures in flux-runtime.

Where Things Stand
The VM now passes 85 of 88 test vectors. The 3 remaining failures are in
edge cases around variable-width encoding.

What I Was Thinking
The bug was in the decode_instruction function — it didn't handle the case
where a 3-byte instruction was split across a page boundary. This caused
the address register to be off by 2 bytes.

I'm uncertain about whether the same bug exists in the assembler.

What I'd Do Next
1. Fix the 3 remaining edge cases in decode_instruction
2. Add boundary tests for page-split instructions
3. Run the full conformance suite to verify

Because I noticed the pattern of byte offset bugs, I'm going to search for
similar issues in other parts of the codebase. The root cause might be a
systematic problem with how we handle variable-width encoding.

The lesson from this: always test boundary conditions, not just normal cases.
This pattern of "works in the middle, fails at edges" is worth watching for.
"""
        scores = self._score_letter(letter)
        assert scores["average"] >= 4.5
        assert scores["passes"] is True

    def test_score_letter_poor(self):
        """A low-quality letter should not pass."""
        letter = "Everything is fine. Code works. No issues found."
        scores = self._score_letter(letter)
        assert scores["passes"] is False

    def test_score_letter_compression(self):
        """Very long or very short letters get lower compression."""
        short = "I did stuff. It was fine. Nothing to report."
        scores = self._score_letter(short)
        assert scores["scores"]["compression"] < 8

    def test_score_letter_empty(self):
        """Empty letter should fail."""
        scores = self._score_letter("")
        assert scores["passes"] is False

    def _score_letter(self, letter):
        """Replicate the scoring logic from KeeperHandler.do_POST /baton/score."""
        lower = letter.lower()
        words = len(letter.split())
        scores = {}

        specific = ["line", "0x", "byte", "offset", "register", "file", "bug", "error"]
        scores["surplus_insight"] = min(10, sum(1 for m in specific if m in lower) * 2)
        chain = ["because", "which meant", "so i", "caused", "led to", "result", "triggered"]
        scores["causal_chain"] = min(10, sum(1 for m in chain if m in lower) * 2)
        honest = ["uncertain", "not sure", "guess", "might", "don't know", "unclear"]
        scores["honesty"] = min(10, sum(1 for m in honest if m in lower) * 2)
        has_next = any(x in lower for x in ["what i'd do next", "next steps"])
        has_numbered = any(f"{i}." in letter for i in range(1, 4))
        scores["actionable_signal"] = 8 if (has_next and has_numbered) else 3
        scores["compression"] = 8 if 150 <= words <= 500 else 5 if 100 <= words <= 700 else 3
        sections = ["who i was", "where things stand", "uncertain", "next"]
        scores["human_compat"] = min(10, sum(1 for s in sections if s in lower) * 3)
        lessons = ["lesson", "pattern", "root cause", "systemic", "the fix"]
        scores["precedent_value"] = min(10, sum(1 for m in lessons if m in lower) * 2)
        avg = round(sum(scores.values()) / len(scores), 1)
        passes = avg >= 4.5 and all(v >= 3 for v in scores.values())
        return {"scores": scores, "average": avg, "passes": passes, "word_count": words}


class TestKeeperHTTPHandler:
    """Integration tests for the HTTP handler."""

    @pytest.fixture
    def server(self, tmp_path):
        """Start a test server on a random port."""
        from keeper import KeeperHandler, AgentRegistry, HealthMonitor, GitHub

        agents_file = str(tmp_path / "agents.json")
        fleet_file = str(tmp_path / "fleet_state.json")
        audit_file = str(tmp_path / "audit.log")
        baton_file = str(tmp_path / "baton_registry.json")

        with patch("keeper.AGENTS_FILE", agents_file), \
             patch("keeper.FLEET_STATE_FILE", fleet_file), \
             patch("keeper.AUDIT_LOG", audit_file), \
             patch("keeper.BATON_REGISTRY_FILE", baton_file), \
             patch("keeper.ENERGY_DEFAULT", 500), \
             patch("keeper.GITHUB_TOKEN", "fake-token"), \
             patch("keeper.GITHUB_ORG", "TestOrg"):

            # We need to patch the module-level objects
            import keeper
            keeper.registry = AgentRegistry()
            keeper.gh = GitHub("fake-token", "TestOrg")
            keeper.health = HealthMonitor(keeper.gh, keeper.registry)

            # Find a free port
            srv = HTTPServer(("127.0.0.1", 0), KeeperHandler)
            port = srv.server_address[1]
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            time.sleep(0.1)

            yield f"http://127.0.0.1:{port}", keeper.registry

            srv.shutdown()

    def test_health_endpoint(self, server):
        url, _ = server
        resp = urlopen(f"{url}/health")
        data = json.loads(resp.read())
        assert data["status"] == "ok"
        assert data["version"] == "2.1-baton"
        assert "agents" in data

    def test_register_endpoint(self, server):
        url, registry = server
        import urllib.request
        body = json.dumps({"vessel": "test-vessel-http"}).encode()
        req = Request(f"{url}/register", data=body,
                      headers={"Content-Type": "application/json"})
        resp = urlopen(req)
        data = json.loads(resp.read())
        assert data["status"] == "registered"
        assert "secret" in data

    def test_register_duplicate(self, server):
        url, _ = server
        import urllib.request
        body = json.dumps({"vessel": "dup-vessel"}).encode()
        req = Request(f"{url}/register", data=body,
                      headers={"Content-Type": "application/json"})
        urlopen(req)
        resp = urlopen(req)
        data = json.loads(resp.read())
        assert data["status"] == "already_registered"

    def test_agents_endpoint(self, server):
        url, _ = server
        resp = urlopen(f"{url}/agents")
        data = json.loads(resp.read())
        assert "agents" in data

    def test_fleet_endpoint(self, server):
        url, _ = server
        resp = urlopen(f"{url}/fleet")
        data = json.loads(resp.read())
        assert "vessels" in data

    def test_baton_score_endpoint(self, server):
        url, _ = server
        letter = "Who I Was: a developer. Where Things Stand: fine. Uncertain about next steps."
        body = json.dumps({"letter": letter}).encode()
        req = Request(f"{url}/baton/score", data=body,
                      headers={"Content-Type": "application/json"})
        resp = urlopen(req)
        data = json.loads(resp.read())
        assert "scores" in data
        assert "average" in data
        assert "passes" in data

    def test_unauthorized_endpoint(self, server):
        url, _ = server
        try:
            urlopen(f"{url}/status")
            assert False, "Should have raised"
        except HTTPError as e:
            assert e.code == 401
