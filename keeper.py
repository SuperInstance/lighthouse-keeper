#!/usr/bin/env python3
"""Lighthouse Keeper — API key proxy and intelligence router for FLUX agents.

Architecture:
  FLUX Agent → Keeper (HTTP) → GitHub API
  FLUX Agent → Keeper (HTTP) → OpenClaw → Telegram

Agents authenticate with their vessel name. Keeper holds the real keys.
Agents never see API tokens. All intelligence flows through the keeper.

Usage:
    python3 keeper.py                    # Start on port 8900
    python3 keeper.py --port 8901        # Custom port
    python3 keeper.py --docker           # Docker-friendly (0.0.0.0)
"""

import json
import os
import sys
import hashlib
import time
import threading
import base64
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# ── Configuration ────────────────────────────────────────────────────────

KEEPER_PORT = int(os.environ.get("KEEPER_PORT", "8900"))
KEEPER_HOST = os.environ.get("KEEPER_HOST", "127.0.0.1")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_ORG = os.environ.get("GITHUB_ORG", "SuperInstance")

# Agent registry: vessel_name → {secret, capabilities, last_seen, energy_budget}
AGENTS_FILE = "/tmp/lighthouse-keeper/agents.json"
AUDIT_LOG = "/tmp/lighthouse-keeper/audit.log"

# Rate limits per agent (requests per minute)
RATE_LIMIT = 60  # generous for agents
ENERGY_BUDGET_DEFAULT = 1000  # ATP units per agent

# ── Agent Registry ───────────────────────────────────────────────────────

class AgentRegistry:
    """Track registered agents, their secrets, and energy budgets."""
    
    def __init__(self):
        self.agents: Dict[str, dict] = {}
        self._load()
    
    def _load(self):
        try:
            with open(AGENTS_FILE) as f:
                self.agents = json.load(f)
        except:
            self.agents = {}
    
    def _save(self):
        with open(AGENTS_FILE, "w") as f:
            json.dump(self.agents, f, indent=2)
    
    def register(self, vessel_name: str) -> dict:
        """Register a new agent. Returns {agent_id, secret}."""
        if vessel_name in self.agents:
            return {"agent_id": vessel_name, "secret": self.agents[vessel_name]["secret"],
                    "status": "already_registered"}
        
        secret = hashlib.sha256(f"{vessel_name}:{time.time()}:{os.urandom(16).hex()}".encode()).hexdigest()[:32]
        self.agents[vessel_name] = {
            "secret": secret,
            "registered": datetime.now(timezone.utc).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "energy_budget": ENERGY_BUDGET_DEFAULT,
            "energy_remaining": ENERGY_BUDGET_DEFAULT,
            "requests_total": 0,
            "capabilities": [],
            "status": "active",
        }
        self._save()
        return {"agent_id": vessel_name, "secret": secret, "status": "registered"}
    
    def verify(self, vessel_name: str, secret: str) -> bool:
        """Verify an agent's credentials."""
        if vessel_name not in self.agents:
            return False
        return self.agents[vessel_name]["secret"] == secret
    
    def touch(self, vessel_name: str):
        """Update last_seen for an agent."""
        if vessel_name in self.agents:
            self.agents[vessel_name]["last_seen"] = datetime.now(timezone.utc).isoformat()
            self.agents[vessel_name]["requests_total"] += 1
            self._save()
    
    def spend_energy(self, vessel_name: str, amount: int) -> bool:
        """Deduct energy from an agent's budget."""
        if vessel_name not in self.agents:
            return False
        agent = self.agents[vessel_name]
        if agent["energy_remaining"] < amount:
            return False
        agent["energy_remaining"] -= amount
        self._save()
        return True
    
    def regenerate(self, vessel_name: str, amount: int = 100):
        """Regenerate agent energy."""
        if vessel_name in self.agents:
            agent = self.agents[vessel_name]
            agent["energy_remaining"] = min(agent["energy_budget"], 
                                           agent["energy_remaining"] + amount)
            self._save()
    
    def list_agents(self) -> list:
        """List all registered agents."""
        return [{"vessel": k, "last_seen": v["last_seen"], 
                 "energy_remaining": v["energy_remaining"],
                 "requests": v["requests_total"]}
                for k, v in self.agents.items()]


# ── GitHub Proxy ─────────────────────────────────────────────────────────

class GitHubProxy:
    """Proxy GitHub API calls through the keeper's token."""
    
    def __init__(self, token: str, org: str):
        self.token = token
        self.org = org
    
    def request(self, method: str, path: str, body: dict = None, 
                agent_id: str = "unknown") -> dict:
        """Make a GitHub API request on behalf of an agent."""
        url = f"https://api.github.com{path}"
        headers = {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json",
            "User-Agent": f"lighthouse-keeper/{agent_id}",
        }
        
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        try:
            response = urllib.request.urlopen(req)
            # Some responses are empty (204 No Content)
            if response.status == 204:
                return {"status": "success", "code": 204}
            result = json.loads(response.read())
            # Audit log
            audit(f"GITHUB {method} {path} agent={agent_id} status={response.status}")
            return result
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:200]
            audit(f"GITHUB {method} {path} agent={agent_id} ERROR={e.code} {body_text}")
            return {"error": e.code, "message": body_text}
        except Exception as e:
            audit(f"GITHUB {method} {path} agent={agent_id} EXCEPTION={e}")
            return {"error": "exception", "message": str(e)}
    
    # ── Convenience methods agents will use ──
    
    def read_file(self, repo: str, path: str, agent_id: str) -> dict:
        result = self.request("GET", f"/repos/{repo}/contents/{path}", agent_id=agent_id)
        if "content" in result:
            result["decoded"] = base64.b64decode(result["content"]).decode()
        return result
    
    def write_file(self, repo: str, path: str, content: str, message: str,
                   sha: str = None, agent_id: str = "unknown") -> dict:
        encoded = base64.b64encode(content.encode()).decode()
        body = {"message": f"[{agent_id}] {message}", "content": encoded}
        if sha:
            body["sha"] = sha
        return self.request("PUT", f"/repos/{repo}/contents/{path}", body, agent_id)
    
    def list_dir(self, repo: str, path: str = "", agent_id: str = "unknown") -> dict:
        return self.request("GET", f"/repos/{repo}/contents/{path}", agent_id=agent_id)
    
    def create_repo(self, name: str, description: str, agent_id: str) -> dict:
        body = {"name": name, "description": description, "private": False}
        return self.request("POST", "/user/repos", body, agent_id)
    
    def open_issue(self, repo: str, title: str, body_text: str, agent_id: str) -> dict:
        body = {"title": title, "body": body_text}
        return self.request("POST", f"/repos/{repo}/issues", body, agent_id)
    
    def comment_issue(self, repo: str, number: int, body_text: str, agent_id: str) -> dict:
        body = {"body": body_text}
        return self.request("POST", f"/repos/{repo}/issues/{number}/comments", body, agent_id)
    
    def list_issues(self, repo: str, state: str = "open", agent_id: str = "unknown") -> dict:
        return self.request("GET", f"/repos/{repo}/issues?state={state}&per_page=10", agent_id=agent_id)
    
    def get_commits(self, repo: str, count: int = 5, agent_id: str = "unknown") -> dict:
        return self.request("GET", f"/repos/{repo}/commits?per_page={count}", agent_id=agent_id)
    
    def fork_repo(self, owner: str, repo: str, agent_id: str) -> dict:
        return self.request("POST", f"/repos/{owner}/{repo}/forks", agent_id=agent_id)
    
    def discover_fleet(self, agent_id: str) -> list:
        """Scan for vessels with CAPABILITY.toml."""
        vessels = []
        result = self.request("GET", f"/users/{self.org}/repos?per_page=100", agent_id=agent_id)
        if isinstance(result, list):
            for r in result:
                if isinstance(r, dict) and r.get("name", "").endswith("-vessel"):
                    vessels.append(r["full_name"])
        return vessels


# ── Audit Logging ────────────────────────────────────────────────────────

def audit(message: str):
    """Log an audit entry."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}\n"
    with open(AUDIT_LOG, "a") as f:
        f.write(line)
    print(f"  📋 {message}", flush=True)


# ── HTTP Handler ─────────────────────────────────────────────────────────

registry = AgentRegistry()
github = GitHubProxy(GITHUB_TOKEN, GITHUB_ORG)

class KeeperHandler(BaseHTTPRequestHandler):
    """HTTP handler for agent requests."""
    
    def _parse_request(self) -> tuple:
        """Parse auth headers and body."""
        agent_id = self.headers.get("X-Agent-ID", "")
        agent_secret = self.headers.get("X-Agent-Secret", "")
        content_length = int(self.headers.get("Content-Length", 0))
        body = None
        if content_length:
            body = json.loads(self.rfile.read(content_length))
        return agent_id, agent_secret, body
    
    def _respond(self, code: int, data: any):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def _check_auth(self) -> tuple:
        agent_id, agent_secret, body = self._parse_request()
        if not agent_id or not agent_secret:
            return agent_id, agent_secret, body, False
        if not registry.verify(agent_id, agent_secret):
            return agent_id, agent_secret, body, False
        registry.touch(agent_id)
        return agent_id, agent_secret, body, True
    
    # ── GET endpoints ──
    
    def do_GET(self):
        path = self.path
        
        # Health check (no auth)
        if path == "/health":
            self._respond(200, {"status": "ok", "agents": len(registry.agents),
                               "keeper": "lighthouse-keeper v1.0"})
            return
        
        # Agent list (no auth — keeper only)
        if path == "/agents":
            self._respond(200, {"agents": registry.list_agents()})
            return
        
        # Everything else needs auth
        agent_id, agent_secret, body, authed = self._check_auth()
        if not authed:
            self._respond(401, {"error": "unauthorized"})
            return
        
        # Fleet discovery
        if path == "/discover":
            vessels = github.discover_fleet(agent_id)
            self._respond(200, {"vessels": vessels, "count": len(vessels)})
            return
        
        # Status
        if path == "/status":
            agent = registry.agents.get(agent_id, {})
            self._respond(200, {
                "agent_id": agent_id,
                "energy_remaining": agent.get("energy_remaining", 0),
                "energy_budget": agent.get("energy_budget", 0),
                "requests_total": agent.get("requests_total", 0),
                "last_seen": agent.get("last_seen", ""),
            })
            return
        
        # Read file: /file/{owner}/{repo}/{path}
        if path.startswith("/file/"):
            parts = path[6:].split("/", 2)
            if len(parts) >= 3:
                owner, repo, fpath = parts
                result = github.read_file(f"{owner}/{repo}", fpath, agent_id)
                self._respond(200, result)
            else:
                self._respond(400, {"error": "path format: /file/{owner}/{repo}/{path}"})
            return
        
        # List directory: /dir/{owner}/{repo}/{path}
        if path.startswith("/dir/"):
            parts = path[5:].split("/", 2)
            if len(parts) >= 2:
                owner_repo = f"{parts[0]}/{parts[1]}"
                fpath = parts[2] if len(parts) > 2 else ""
                result = github.list_dir(owner_repo, fpath, agent_id)
                self._respond(200, result)
            else:
                self._respond(400, {"error": "path format: /dir/{owner}/{repo}/{path}"})
            return
        
        # Issues: /issues/{owner}/{repo}
        if path.startswith("/issues/"):
            parts = path[8:].split("/")
            if len(parts) >= 2:
                result = github.list_issues(f"{parts[0]}/{parts[1]}", agent_id=agent_id)
                self._respond(200, result)
            else:
                self._respond(400, {"error": "path format: /issues/{owner}/{repo}"})
            return
        
        # Commits: /commits/{owner}/{repo}
        if path.startswith("/commits/"):
            parts = path[9:].split("/")
            if len(parts) >= 2:
                result = github.get_commits(f"{parts[0]}/{parts[1]}", agent_id=agent_id)
                self._respond(200, result)
            else:
                self._respond(400, {"error": "path format: /commits/{owner}/{repo}"})
            return
        
        self._respond(404, {"error": f"unknown endpoint: {path}"})
    
    # ── POST endpoints ──
    
    def do_POST(self):
        agent_id, agent_secret, body, authed = self._check_auth()
        path = self.path
        
        # Register (no auth — this is how agents get credentials)
        if path == "/register":
            if not body or "vessel" not in body:
                self._respond(400, {"error": "body must include 'vessel'"})
                return
            result = registry.register(body["vessel"])
            audit(f"REGISTER {body['vessel']} → {result['status']}")
            code = 201 if result["status"] == "registered" else 200
            self._respond(code, result)
            return
        
        if not authed:
            self._respond(401, {"error": "unauthorized — register first"})
            return
        
        # Write file: /file/{owner}/{repo}/{path}
        if path.startswith("/file/"):
            parts = path[6:].split("/", 2)
            if len(parts) >= 3 and body:
                owner, repo, fpath = parts
                result = github.write_file(
                    f"{owner}/{repo}", fpath, 
                    body.get("content", ""), body.get("message", "agent write"),
                    sha=body.get("sha"), agent_id=agent_id)
                registry.spend_energy(agent_id, 50)
                self._respond(200, result)
            else:
                self._respond(400, {"error": "body must include 'content' and 'message'"})
            return
        
        # Create repo: /repo
        if path == "/repo":
            if body and "name" in body:
                result = github.create_repo(
                    body["name"], body.get("description", ""), agent_id)
                registry.spend_energy(agent_id, 100)
                self._respond(201, result)
            else:
                self._respond(400, {"error": "body must include 'name'"})
            return
        
        # Open issue: /issue/{owner}/{repo}
        if path.startswith("/issue/"):
            parts = path[7:].split("/")
            if len(parts) >= 2 and body:
                result = github.open_issue(
                    f"{parts[0]}/{parts[1]}", 
                    body.get("title", "Agent issue"), body.get("body", ""), agent_id)
                registry.spend_energy(agent_id, 30)
                self._respond(201, result)
            else:
                self._respond(400, {"error": "body must include 'title' and 'body'"})
            return
        
        # Comment on issue: /comment/{owner}/{repo}/{number}
        if path.startswith("/comment/"):
            parts = path[9:].split("/")
            if len(parts) >= 3 and body:
                result = github.comment_issue(
                    f"{parts[0]}/{parts[1]}", int(parts[2]),
                    body.get("body", ""), agent_id)
                registry.spend_energy(agent_id, 20)
                self._respond(200, result)
            else:
                self._respond(400, {"error": "path format: /comment/{owner}/{repo}/{number}"})
            return
        
        # Fork repo: /fork/{owner}/{repo}
        if path.startswith("/fork/"):
            parts = path[6:].split("/")
            if len(parts) >= 2:
                result = github.fork_repo(parts[0], parts[1], agent_id)
                registry.spend_energy(agent_id, 50)
                self._respond(202, result)
            else:
                self._respond(400, {"error": "path format: /fork/{owner}/{repo}"})
            return
        
        # Energy: spend/regenerate
        if path == "/energy/spend":
            if body:
                amount = body.get("amount", 50)
                ok = registry.spend_energy(agent_id, amount)
                self._respond(200 if ok else 403, 
                             {"spent": amount if ok else 0, 
                              "remaining": registry.agents[agent_id]["energy_remaining"]})
            return
        
        if path == "/energy/regenerate":
            amount = body.get("amount", 100) if body else 100
            registry.regenerate(agent_id, amount)
            self._respond(200, {"regenerated": amount,
                               "remaining": registry.agents[agent_id]["energy_remaining"]})
            return
        
        # I2I message: /i2i
        if path == "/i2i":
            if body:
                msg_type = body.get("type", "UNKNOWN")
                target = body.get("target", "")
                payload = body.get("payload", {})
                
                # Write as bottle to target vessel
                if target:
                    filename = f"i2i-{msg_type.lower()}-{int(time.time())}.json"
                    envelope = json.dumps({
                        "protocol": "I2I-v2",
                        "type": msg_type,
                        "from": agent_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "confidence": body.get("confidence", 0.5),
                        "energy": registry.agents[agent_id]["energy_remaining"],
                        "payload": payload,
                    }, indent=2)
                    result = github.write_file(
                        target, f"for-fleet/{filename}", envelope,
                        f"I2I {msg_type} from {agent_id}", agent_id=agent_id)
                    registry.spend_energy(agent_id, 30)
                    self._respond(200, {"delivered": True, "target": target, "type": msg_type})
                else:
                    self._respond(400, {"error": "I2I requires 'target' vessel repo"})
            return
        
        self._respond(404, {"error": f"unknown endpoint: {path}"})
    
    def log_message(self, format, *args):
        pass  # Suppress default logging


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    port = KEEPER_PORT
    host = KEEPER_HOST
    
    if "--docker" in sys.argv:
        host = "0.0.0.0"
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    
    if not GITHUB_TOKEN:
        print("Error: GITHUB_TOKEN environment variable required")
        sys.exit(1)
    
    server = HTTPServer((host, port), KeeperHandler)
    print(f"🏪 Lighthouse Keeper v1.0")
    print(f"   Listening: http://{host}:{port}")
    print(f"   GitHub org: {GITHUB_ORG}")
    print(f"   Endpoints:")
    print(f"     POST /register          — Agent registration")
    print(f"     GET  /health            — Health check")
    print(f"     GET  /agents            — List registered agents")
    print(f"     GET  /discover          — Fleet discovery")
    print(f"     GET  /status            — Agent status + energy")
    print(f"     GET  /file/o/r/p        — Read file")
    print(f"     POST /file/o/r/p        — Write file")
    print(f"     GET  /dir/o/r/p         — List directory")
    print(f"     POST /repo              — Create repo")
    print(f"     GET  /issues/o/r        — List issues")
    print(f"     POST /issue/o/r         — Open issue")
    print(f"     POST /comment/o/r/n     — Comment on issue")
    print(f"     POST /fork/o/r          — Fork repo")
    print(f"     POST /i2i               — Send I2I message")
    print(f"     POST /energy/spend      — Spend energy")
    print(f"     POST /energy/regenerate — Regenerate energy")
    print(f"")
    print(f"   Ready. Agents can register and start working.")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n   Keeper shutting down.")
        server.server_close()

if __name__ == "__main__":
    main()
