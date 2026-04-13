#!/usr/bin/env python3
"""Lighthouse Keeper v2 — Lean, layered fleet management.

Layers:
  1. API Proxy      — agents route through keeper, never see keys
  2. Health Monitor  — incremental "are you ok" checks, not full scans
  3. Intervention    — read diary, understand last intent, reboot cleanly
  4. Fleet Dashboard — real-time fleet state from accumulated data

Design principles:
  - Incremental: check a few agents per cycle, not all at once
  - Git-native: state in files, not databases
  - Read-before-write: understand before intervening
  - Cheap checks: commit timestamps are free, file reads cost API calls
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
from collections import OrderedDict
from typing import Any, Dict, List, Optional

# ── Configuration ──

KEEPER_PORT = int(os.environ.get("KEEPER_PORT", "8900"))
KEEPER_HOST = os.environ.get("KEEPER_HOST", "127.0.0.1")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_ORG = os.environ.get("GITHUB_ORG", "SuperInstance")

AGENTS_FILE = "/tmp/lighthouse-keeper/agents.json"
FLEET_STATE_FILE = "/tmp/lighthouse-keeper/fleet_state.json"
AUDIT_LOG = "/tmp/lighthouse-keeper/audit.log"

# ── Rate Limiter ──
class RateLimiter:
    """Token bucket rate limiter per agent."""
    def __init__(self) -> None:
        self.buckets: Dict[str, Dict[str, Any]] = {}  # agent_id -> {tokens, last_refill, max_tokens, refill_rate}
    
    def configure(self, agent_id: str, max_tokens: int = 100, refill_rate: float = 10) -> None:
        """Configure rate limit for an agent. refill_rate = tokens/minute."""
        if not agent_id:
            return
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be positive")
        self.buckets[agent_id] = {
            "tokens": float(max_tokens),
            "last_refill": time.time(),
            "max_tokens": float(max_tokens),
            "refill_rate": float(refill_rate)  # tokens per minute
        }
    
    def consume(self, agent_id: str, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        if not agent_id:
            return False
        if tokens <= 0:
            return True  # No cost for zero or negative tokens
        if agent_id not in self.buckets:
            self.configure(agent_id)
        
        b = self.buckets[agent_id]
        now = time.time()
        elapsed = now - b["last_refill"]
        b["tokens"] = min(b["max_tokens"], b["tokens"] + (elapsed / 60.0) * b["refill_rate"])
        b["last_refill"] = now
        
        if b["tokens"] >= tokens:
            b["tokens"] -= tokens
            return True
        return False

rate_limiter = RateLimiter()

def log_audit(msg: str) -> None:
    """Write audit log entry with error handling."""
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(f"{ts_now()} {msg}\n")
    except (IOError, OSError) as e:
        print(f"ERROR writing audit log: {e}")



BATON_REGISTRY_FILE = "/tmp/lighthouse-keeper/baton_registry.json"

HEALTH_CHECK_INTERVAL = int(os.environ.get("HEALTH_INTERVAL", "60"))  # seconds between ticks
AGENTS_PER_TICK = int(os.environ.get("HEALTH_PER_TICK", "3"))  # agents checked per tick
MISSED_BEFORE_ALERT = int(os.environ.get("HEALTH_MISSED_ALERT", "3"))
MISSED_BEFORE_REBOOT = int(os.environ.get("HEALTH_MISSED_REBOOT", "6"))
ENERGY_DEFAULT = int(os.environ.get("ENERGY_DEFAULT", "1000"))

# ── Utilities ──

def audit(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with open(AUDIT_LOG, "a") as f:
        f.write(f"[{ts}] {msg}\n")

def ts_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_json(path: str, default: Optional[Any] = None) -> Optional[Any]:
    """Load JSON from file with error handling."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return default if default is not None else {}
    except (json.JSONDecodeError, IOError, OSError) as e:
        audit(f"ERROR loading JSON from {path}: {e}")
        return default if default is not None else {}

def save_json(path: str, data: Any) -> None:
    """Save data to JSON file with error handling."""
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except (TypeError, IOError, OSError) as e:
        audit(f"ERROR saving JSON to {path}: {e}")

# ── GitHub API ──

class GitHub:
    """Thin GitHub API wrapper. All calls go through here for auditing."""
    
    def __init__(self, token: str, org: str):
        self.token = token
        self.org = org
        self._headers = {
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "User-Agent": "lighthouse-keeper/2.0",
        }
        self._call_count = 0
    
    def _req(self, method: str, path: str, body=None) -> dict:
        url = f"https://api.github.com{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers, method=method)
        self._call_count += 1
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            if resp.status == 204:
                return {"_status": 204}
            raw = resp.read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()[:200]
            return {"_error": e.code, "_message": err_body}
        except Exception as e:
            return {"_error": "timeout", "_message": str(e)[:100]}
    
    def get(self, path: str) -> dict:
        return self._req("GET", path)
    
    def post(self, path: str, body: dict) -> dict:
        return self._req("POST", path, body)
    
    def put(self, path: str, body: dict) -> dict:
        return self._req("PUT", path, body)
    
    def read_file(self, repo: str, path: str) -> Optional[tuple[str, Optional[str]]]:
        """Read a file from a repo. Returns (content, sha) or None."""
        try:
            data = self.get(f"/repos/{repo}/contents/{path}")
            if "_error" in data:
                return None
            if "content" in data:
                content = base64.b64decode(data["content"]).decode()
                sha = data.get("sha")
                return content, sha
            return None, None
        except (ValueError, KeyError, TypeError) as e:
            audit(f"ERROR reading file {repo}/{path}: {e}")
            return None
    
    def write_file(self, repo: str, path: str, content: str, message: str, sha: Optional[str] = None) -> dict:
        encoded = base64.b64encode(content.encode()).decode()
        body = {"message": message, "content": encoded}
        if sha:
            body["sha"] = sha
        return self.put(f"/repos/{repo}/contents/{path}", body)
    
    def last_commit_age(self, repo: str) -> Optional[int]:
        """Seconds since last commit. Cheap — 1 API call."""
        commits = self.get(f"/repos/{repo}/commits?per_page=1")
        if isinstance(commits, list) and commits:
            date_str = commits[0].get("commit", {}).get("author", {}).get("date", "")
            if date_str:
                last = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return int((datetime.now(timezone.utc) - last).total_seconds())
        return None
    
    def discover_vessels(self) -> List[str]:
        """Find all vessel repos."""
        vessels = []
        repos = self.get(f"/users/{self.org}/repos?per_page=100")
        if isinstance(repos, list):
            for r in repos:
                name = r.get("name", "")
                if "-vessel" in name or name.startswith("flux-agent") or name.startswith("flux-"):
                    vessels.append(r["full_name"])
        return vessels
    
    def _raw_request(self, method: str, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Raw GitHub API request — for proxy use."""
        url = f"https://api.github.com{path}"
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json"
        }
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return {"error": e.reason, "code": e.code}
        except Exception as e:
            return {"error": str(e)}


# ── Agent Registry ──

class AgentRegistry:
    """Registered agents with credentials and energy budgets."""
    
    def __init__(self):
        self.agents = load_json(AGENTS_FILE, {})
        self._lock = threading.Lock()
    
    def _save(self) -> None:
        save_json(AGENTS_FILE, self.agents)
    
    def register(self, vessel: str) -> dict:
        """Register a new agent vessel. Returns registration info."""
        if not vessel or not isinstance(vessel, str):
            return {"error": "vessel must be a non-empty string", "status": "error"}
        
        with self._lock:
            if vessel in self.agents:
                return {"agent_id": vessel, "secret": self.agents[vessel]["secret"],
                        "status": "already_registered"}
            
            try:
                secret = hashlib.sha256(f"{vessel}:{time.time()}:{os.urandom(8).hex()}".encode()).hexdigest()[:32]
                self.agents[vessel] = {
                    "secret": secret,
                    "registered": ts_now(),
                    "last_seen": ts_now(),
                    "energy_budget": ENERGY_DEFAULT,
                    "energy_remaining": ENERGY_DEFAULT,
                    "requests": 0,
                    "status": "active",
                }
                self._save()
                return {"agent_id": vessel, "secret": secret, "status": "registered"}
            except Exception as e:
                audit(f"ERROR registering vessel {vessel}: {e}")
                return {"error": str(e), "status": "error"}
    
    def verify(self, vessel: str, secret: str) -> bool:
        """Verify agent credentials. Returns True if valid."""
        if not vessel or not secret:
            return False
        agent = self.agents.get(vessel)
        return agent and agent["secret"] == secret
    
    def touch(self, vessel: str) -> None:
        """Update agent last_seen timestamp and request count."""
        if not vessel:
            return
        with self._lock:
            if vessel in self.agents:
                try:
                    self.agents[vessel]["last_seen"] = ts_now()
                    self.agents[vessel]["requests"] += 1
                    self._save()
                except (KeyError, TypeError) as e:
                    audit(f"ERROR touching vessel {vessel}: {e}")
    
    def spend_energy(self, vessel: str, amount: int) -> bool:
        """Spend energy from agent budget. Returns True if successful."""
        if not vessel or amount <= 0:
            return False
        with self._lock:
            agent = self.agents.get(vessel)
            if not agent:
                return False
            try:
                if agent["energy_remaining"] < amount:
                    return False
                agent["energy_remaining"] -= amount
                self._save()
                return True
            except (KeyError, TypeError) as e:
                audit(f"ERROR spending energy for vessel {vessel}: {e}")
                return False
    
    def regenerate(self, vessel: str, amount: int = 100) -> None:
        """Regenerate energy for an agent."""
        if not vessel or amount <= 0:
            return
        with self._lock:
            agent = self.agents.get(vessel)
            if agent:
                try:
                    agent["energy_remaining"] = min(
                        agent["energy_budget"], agent["energy_remaining"] + amount)
                    self._save()
                except (KeyError, TypeError) as e:
                    audit(f"ERROR regenerating energy for vessel {vessel}: {e}")
    
    def list_agents(self) -> list:
        return [{"vessel": k, "last_seen": v["last_seen"],
                 "energy": v["energy_remaining"], "requests": v["requests"]}
                for k, v in self.agents.items()]


# ── Fleet Health Monitor ──

class HealthMonitor:
    """Incremental fleet health monitoring.
    
    Checks AGENTS_PER_TICK vessels per tick, cycling through all vessels.
    Keeps fleet state in a JSON file that the dashboard can read.
    Only does expensive operations (file reads) when intervention is needed.
    """
    
    def __init__(self, github: GitHub, registry: AgentRegistry) -> None:
        self.gh = github
        self.registry = registry
        self.fleet_state = load_json(FLEET_STATE_FILE, {"vessels": {}, "last_full_scan": None})
        self._check_index = 0  # Round-robin index
        self._running = False
    
    def _vessel_list(self) -> List[str]:
        """Get all vessels to monitor — registered agents + discovered vessels."""
        registered = list(self.registry.agents.keys())
        # Also include vessels from fleet state
        known = list(self.fleet_state.get("vessels", {}).keys())
        # De-dup
        all_vessels = list(dict.fromkeys(known + registered))
        return all_vessels
    
    def check_one(self, repo: str) -> Dict[str, Any]:
        """Check a single vessel's health. Cheap: 1 API call (commits)."""
        age = self.gh.last_commit_age(repo)
        
        if age is None:
            status = "unknown"
        elif age < 300:
            status = "active"
        elif age < 1800:
            status = "idle"
        elif age < 86400:
            status = "stale"
        else:
            status = "dead"
        
        # Get previous state
        prev = self.fleet_state.get("vessels", {}).get(repo, {})
        missed = prev.get("missed", 0)
        
        if status in ("active",):
            missed = 0
        else:
            missed += 1
        
        state = {
            "repo": repo,
            "status": status,
            "age": age,
            "missed": missed,
            "last_checked": ts_now(),
            "last_active": prev.get("last_active", ts_now() if status == "active" else None),
            "intervention": None,
        }
        
        if status == "active":
            state["last_active"] = ts_now()
        
        # Determine intervention
        if missed >= MISSED_BEFORE_REBOOT:
            state["intervention"] = "reboot"
        elif missed >= MISSED_BEFORE_ALERT:
            state["intervention"] = "alert"
        
        # Update fleet state
        if "vessels" not in self.fleet_state:
            self.fleet_state["vessels"] = {}
        self.fleet_state["vessels"][repo] = state
        save_json(FLEET_STATE_FILE, self.fleet_state)
        
        return state
    
    def intervene(self, repo: str, state: Dict[str, Any]) -> None:
        """Intervene with an unresponsive agent. Expensive: reads diary."""
        name = repo.split("/")[-1]
        missed = state["missed"]
        intervention = state["intervention"]
        
        if intervention == "alert":
            # Send a health check bottle (cheap — 1 write)
            content = json.dumps({
                "type": "HEALTH_CHECK",
                "from": "keeper",
                "timestamp": ts_now(),
                "missed_cycles": missed,
                "message": "Are you ok? Push a commit or update STATUS.json to respond.",
            }, indent=2)
            self.gh.write_file(repo, f"for-fleet/health-check.json", content,
                             f"keeper: health check (missed {missed} cycles)")
            audit(f"HEALTH_ALERT {name} missed={missed}")
        
        elif intervention == "reboot":
            # BatON-native reboot: read .baton/ first, then diary fallback
            baton_handoff = None
            baton_state = None
            
            # Try to read baton (the modern path)
            handoff_raw, _ = self.gh.read_file(repo, ".baton/CURRENT/HANDOFF.md") or (None, None)
            state_raw, _ = self.gh.read_file(repo, ".baton/CURRENT/STATE.json") or (None, None)
            gen_raw, _ = self.gh.read_file(repo, ".baton/GENERATION") or (None, None)
            
            if handoff_raw:
                baton_handoff = handoff_raw
            if state_raw:
                try: baton_state = json.loads(state_raw)
                except: pass
            
            # Fallback: read diary if no baton
            diary, _ = self.gh.read_file(repo, "DIARY/log.md") or (None, None)
            bootcamp, _ = self.gh.read_file(repo, "BOOTCAMP.md") or (None, None)
            
            last_intent = ""
            if baton_handoff:
                last_intent = baton_handoff[-500:]  # Latest handoff letter
            elif diary:
                lines = [l.strip() for l in diary.split("\n") if l.strip() and not l.startswith("#")]
                last_intent = "\n".join(lines[-5:]) if lines else "empty diary"
            
            last_status = ""
            if baton_state:
                last_status = json.dumps(baton_state, indent=2)
            else:
                status_json, _ = self.gh.read_file(repo, "STATUS.json") or (None, None)
                if status_json:
                    try: last_status = json.dumps(json.loads(status_json), indent=2)
                    except: last_status = status_json[:200]
            
            gen_info = f"\n**Baton generation:** {gen_raw.strip()}" if gen_raw else "\n**No baton found — legacy agent**"
            
            # File reboot issue
            body = {
                "title": f"🔄 Reboot Required — {name}",
                "body": f"# Agent Reboot\n\n"
                        f"**Silent for:** {missed} check cycles\n"
                        f"**Last commit:** {state.get('age', '?')}s ago\n\n"
                        f"## Last Intentions (from diary)\n"
                        f"```\n{last_intent}\n```\n\n"
                        f"## Last Status\n"
                        f"```json\n{last_status}\n```\n\n"
                        f"## Recovery\n"
                        f"Bootcamp available: {'Yes' if bootcamp else 'No'}\n"
                        f"1. Read BOOTCAMP.md → learn who this agent was\n"
                        f"2. Read DIARY/ → understand what they were doing\n"
                        f"3. Spawn replacement with same vessel\n"
                        f"4. Replacement reads diary, picks up where they left off\n"
                        f"5. Very little work product lost — git IS the brain\n"
            }
            self.gh.post(f"/repos/{repo}/issues", body)
            
            # Write reboot state file
            self.gh.write_file(repo, "REBOOT-STATE.md",
                f"# 🔄 Reboot State\n\n"
                f"Checked: {ts_now()}\n"
                f"Missed: {missed} cycles\n"
                f"Action: spawn replacement, read diary, continue\n",
                f"keeper: REBOOT_REQUIRED after {missed} silent cycles")
            
            audit(f"REBOOT_REQUIRED {name} missed={missed} last_intent={last_intent[:80]}")
    
    def tick(self) -> List[Dict[str, Any]]:
        """Run one incremental health check tick."""
        vessels = self._vessel_list()
        if not vessels:
            return
        
        # Check AGENTS_PER_TICK vessels, round-robin
        checked = []
        for i in range(min(AGENTS_PER_TICK, len(vessels))):
            idx = (self._check_index + i) % len(vessels)
            repo = vessels[idx]
            state = self.check_one(repo)
            checked.append(state)
            
            # Intervene if needed
            if state.get("intervention"):
                self.intervene(repo, state)
        
        self._check_index = (self._check_index + AGENTS_PER_TICK) % len(vessels)
        
        return checked
    
    def run_forever(self) -> None:
        """Background health monitoring loop."""
        self._running = True
        while self._running:
            try:
                # Refresh vessel list periodically
                if self._check_index == 0:
                    discovered = self.gh.discover_vessels()
                    for v in discovered:
                        if v not in self.fleet_state.get("vessels", {}):
                            self.fleet_state.setdefault("vessels", {})[v] = {
                                "repo": v, "status": "new", "missed": 0,
                                "last_checked": ts_now()
                            }
                
                checked = self.tick()
                active = sum(1 for c in checked if c["status"] == "active")
                alerts = sum(1 for c in checked if c.get("intervention"))
                print(f"  🏥 tick: {len(checked)} checked, {active} active, {alerts} alerts | API calls: {self.gh._call_count}")
                
            except Exception as e:
                print(f"  ❌ health tick error: {e}")
            
            time.sleep(HEALTH_CHECK_INTERVAL)
    
    def stop(self) -> None:
        self._running = False


# ── HTTP Handler (v2 — includes health dashboard) ──

registry = AgentRegistry()
gh = GitHub(GITHUB_TOKEN, GITHUB_ORG)
health = HealthMonitor(gh, registry)

class KeeperHandler(BaseHTTPRequestHandler):
    
    def _parse(self) -> tuple[str, str, Optional[Dict[str, Any]]]:
        agent_id = self.headers.get("X-Agent-ID", "")
        secret = self.headers.get("X-Agent-Secret", "")
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else None
        except (ValueError, json.JSONDecodeError):
            body = None
        return agent_id, secret, body
    
    def _json(self, code: int, data: Any) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode())
    
    def _auth(self) -> tuple[str, str, Optional[Dict[str, Any]], bool]:
        aid, secret, body = self._parse()
        if not aid or not secret or not registry.verify(aid, secret):
            return aid, secret, body, False
        registry.touch(aid)
        return aid, secret, body, True
    
    def do_OPTIONS(self) -> None:
        self._json(200, {"ok": True})
    
    # ── GET ──
    
    def do_GET(self) -> None:
        p = self.path.split("?")[0]
        
        if p == "/health":
            self._json(200, {"status": "ok", "version": "2.1-baton", "agents": len(registry.agents),
                            "api_calls": gh._call_count})
            return
        
        if p == "/agents":
            self._json(200, {"agents": registry.list_agents()})
            return
        
        if p == "/fleet":
            self._json(200, health.fleet_state)
            return
        
        # Tender endpoints — liaison vessel tracking
        if p == "/tender/status":
            tender_state = load_json("/tmp/lighthouse-keeper/tender_state.json", {"messages": [], "stats": {}})
            self._json(200, tender_state)
            return
        
        if p == "/tender/pending":
            tender_state = load_json("/tmp/lighthouse-keeper/tender_state.json", {"messages": []})
            pending = [m for m in tender_state.get("messages", []) if m.get("status") == "pending"]
            self._json(200, {"pending": pending, "count": len(pending)})
            return
        
        if p == "/baton/registry":
            self._json(200, load_json(BATON_REGISTRY_FILE, {"vessels": {}}))
            return
        
        if p.startswith("/baton/") and p.endswith("/autobiography"):
            # /baton/{owner}/{repo}/autobiography
            parts = p[7:].replace("/autobiography", "").split("/")
            if len(parts) >= 2:
                repo = f"{parts[0]}/{parts[1]}"
                content = gh.read_file(repo, ".baton/AUTOBIOGRAPHY.md")
                if isinstance(content, tuple):
                    self._json(200, {"content": content[0]})
                else:
                    self._json(200, {"content": None})
            return
        
        if p == "/fleet/dashboard":
            # HTML dashboard
            state = health.fleet_state.get("vessels", {})
            vessels = sorted(state.items(), key=lambda x: x[1].get("missed", 0), reverse=True)
            
            rows = ""
            for repo, v in vessels:
                s = v.get("status", "?")
                emoji = {"active": "🟢", "idle": "🟡", "stale": "🟠", "dead": "🔴", "unknown": "⚪", "new": "🔵"}.get(s, "⚪")
                age = v.get("age")
                age_str = f"{int(age/60)}m" if age and age < 3600 else f"{int(age/3600)}h" if age else "?"
                missed = v.get("missed", 0)
                intervention = v.get("intervention", "")
                int_emoji = "⚠️" if intervention == "alert" else "🔄" if intervention == "reboot" else ""
                rows += f"<tr><td>{emoji}</td><td>{repo.split('/')[-1]}</td><td>{age_str}</td><td>{missed}</td><td>{int_emoji} {intervention}</td></tr>"
            
            html = f"""<!DOCTYPE html><html><head><title>Fleet Dashboard</title>
            <meta http-equiv="refresh" content="30">
            <style>body{{font-family:monospace;background:#1a1a2e;color:#eee;padding:2rem}}
            table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #333}}
            th{{color:#0f0}}</style></head><body>
            <h1>🏪 Fleet Dashboard</h1>
            <p>Last updated: {ts_now()} | Agents: {len(registry.agents)} | Vessels: {len(state)}</p>
            <table><tr><th></th><th>Vessel</th><th>Age</th><th>Missed</th><th>Intervention</th></tr>
            {rows}</table></body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
            return
        
        # Auth-required GET endpoints
        aid, secret, body, authed = self._auth()
        if not authed:
            self._json(401, {"error": "unauthorized"})
            return
        
        if p == "/discover":
            vessels = gh.discover_vessels(aid)
            self._json(200, {"vessels": vessels, "count": len(vessels)})
            return
        
        if p == "/status":
            agent = registry.agents.get(aid, {})
            self._json(200, {"agent_id": aid, "energy": agent.get("energy_remaining", 0),
                            "budget": agent.get("energy_budget", 0), "requests": agent.get("requests", 0)})
            return
        
        if p.startswith("/file/"):
            parts = p[6:].split("/", 2)
            if len(parts) >= 3:
                result = gh.read_file(f"{parts[0]}/{parts[1]}", parts[2])
                if isinstance(result, tuple):
                    decoded, sha = result
                    self._json(200, {"content": decoded, "sha": sha})
                else:
                    self._json(200, {"content": None})
            return
        
        if p.startswith("/dir/"):
            parts = p[5:].split("/", 2)
            if len(parts) >= 2:
                fpath = parts[2] if len(parts) > 2 else ""
                result = gh.get(f"/repos/{parts[0]}/{parts[1]}/contents/{fpath}")
                self._json(200, result)
            return
        
        if p.startswith("/issues/"):
            parts = p[8:].split("/")
            if len(parts) >= 2:
                result = gh.get(f"/repos/{parts[0]}/{parts[1]}/issues?state=open&per_page=10")
                self._json(200, result)
            return
        
        if p.startswith("/commits/"):
            parts = p[9:].split("/")
            if len(parts) >= 2:
                result = gh.get(f"/repos/{parts[0]}/{parts[1]}/commits?per_page=5")
                self._json(200, result)
            return
        
        self._json(404, {"error": f"unknown: {p}"})
    
    # ── POST ──
    
    def do_POST(self) -> None:
        p = self.path
        aid, secret, body = self._parse()
        
        # Register (no auth)
        if p == "/register":
            if not body or "vessel" not in body:
                self._json(400, {"error": "need 'vessel'"})
                return
            result = registry.register(body["vessel"])
            audit(f"REGISTER {body['vessel']} → {result['status']}")
            self._json(201 if result["status"] == "registered" else 200, result)
            return
        
        # Baton score (no auth — utility endpoint)
        if p == "/baton/score" and body and body.get("letter"):
            letter = body["letter"]
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
            self._json(200, {"scores": scores, "average": avg, "passes": passes, "word_count": words})
            return
        
        # Auth required for everything else
        if not registry.verify(aid, secret):
            self._json(401, {"error": "unauthorized"})
            return
        registry.touch(aid)
        
        # ── Proxy endpoints ──
        
        if p.startswith("/proxy/github"):
            # Proxy GitHub API calls - agents never see tokens
            if not body or "path" not in body:
                self._json(400, {"error": "need 'path' in request body"})
                return
            if "method" not in body or body["method"] not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
                self._json(400, {"error": "need valid 'method' (GET, POST, PUT, DELETE, PATCH)"})
                return
            
            method = body["method"]
            path = body["path"]
            data = body.get("data")
            
            # Rate limit check
            if not rate_limiter.consume(aid, tokens=1):
                self._json(429, {"error": "rate limit exceeded"})
                return
            
            log_audit(f"PROXY_GITHUB agent={aid} method={method} path={path}")
            result = gh._raw_request(method, path, data)
            
            # Log errors from GitHub
            if "error" in result:
                log_audit(f"PROXY_GITHUB_ERROR agent={aid} method={method} path={path} error={result['error']}")
            
            self._json(200 if "error" not in result else 502, result)
            return
        
        if p == "/proxy/model":
            # Proxy model API calls with token budget tracking
            if not body or "model" not in body:
                self._json(400, {"error": "need 'model' in request body"})
                return
            if "messages" not in body or not isinstance(body["messages"], list):
                self._json(400, {"error": "need 'messages' array in request body"})
                return
            
            model = body["model"]
            messages = body["messages"]
            temperature = body.get("temperature", 0.7)
            max_tokens = body.get("max_tokens", 1000)
            
            # Validate inputs
            if not isinstance(model, str) or not model:
                self._json(400, {"error": "'model' must be a non-empty string"})
                return
            if not isinstance(temperature, (int, float)) or temperature < 0 or temperature > 2:
                self._json(400, {"error": "'temperature' must be a number between 0 and 2"})
                return
            if not isinstance(max_tokens, int) or max_tokens <= 0:
                self._json(400, {"error": "'max_tokens' must be a positive integer"})
                return
            for i, msg in enumerate(messages):
                if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                    self._json(400, {"error": f"message[{i}] must have 'role' and 'content' fields"})
                    return
            
            # Energy cost based on max_tokens
            energy_cost = max_tokens // 10
            if not registry.spend_energy(aid, energy_cost):
                self._json(403, {"error": "insufficient energy", "required": energy_cost})
                return
            
            log_audit(f"PROXY_MODEL agent={aid} model={model} tokens={max_tokens}")
            
            # Mock response for now - in production, this would call the actual model API
            result = {
                "model": model,
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": f"[PROXY: Model call for {model} with {len(messages)} messages]"
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": sum(len(msg.get("content", "")) // 4 for msg in messages),
                    "completion_tokens": max_tokens,
                    "total_tokens": max_tokens + sum(len(msg.get("content", "")) // 4 for msg in messages)
                }
            }
            
            self._json(200, result)
            return

        if p.startswith("/file/") and body:
            parts = p[6:].split("/", 2)
            if len(parts) >= 3:
                result = gh.write_file(f"{parts[0]}/{parts[1]}", parts[2],
                    body.get("content", ""), body.get("message", "agent write"),
                    sha=body.get("sha"))
                registry.spend_energy(aid, 50)
                audit(f"WRITE {parts[0]}/{parts[1]}/{parts[2]} agent={aid}")
                self._json(200, result)
            return
        
        if p == "/repo" and body:
            result = gh.post("/user/repos", {"name": body["name"],
                            "description": body.get("description", "")})
            registry.spend_energy(aid, 100)
            audit(f"CREATE_REPO {body['name']} agent={aid}")
            self._json(201, result)
            return
        
        if p.startswith("/issue/") and body:
            parts = p[7:].split("/")
            if len(parts) >= 2:
                result = gh.post(f"/repos/{parts[0]}/{parts[1]}/issues",
                    {"title": body.get("title", ""), "body": body.get("body", "")})
                registry.spend_energy(aid, 30)
                self._json(201, result)
            return
        
        if p.startswith("/comment/") and body:
            parts = p[9:].split("/")
            if len(parts) >= 3:
                result = gh.post(f"/repos/{parts[0]}/{parts[1]}/issues/{parts[2]}/comments",
                    {"body": body.get("body", "")})
                registry.spend_energy(aid, 20)
                self._json(200, result)
            return
        
        if p.startswith("/fork/"):
            parts = p[6:].split("/")
            if len(parts) >= 2:
                result = gh.post(f"/repos/{parts[0]}/{parts[1]}/forks", {})
                registry.spend_energy(aid, 50)
                self._json(202, result)
            return
        
        if p == "/i2i" and body:
            target = body.get("target", "")
            if target:
                envelope = json.dumps({
                    "protocol": "I2I-v2", "type": body.get("type", "UNKNOWN"),
                    "from": aid, "timestamp": ts_now(),
                    "confidence": body.get("confidence", 0.5),
                    "energy": registry.agents.get(aid, {}).get("energy_remaining", 0),
                    "payload": body.get("payload", {}),
                }, indent=2)
                filename = f"for-fleet/i2i-{body.get('type','msg').lower()}-{int(time.time())}.json"
                gh.write_file(target, filename, envelope,
                            f"I2I {body.get('type','MSG')} from {aid}")
                registry.spend_energy(aid, 30)
                self._json(200, {"delivered": True, "target": target})
            else:
                self._json(400, {"error": "need 'target'"})
            return
        
        if p == "/energy/spend" and body:
            ok = registry.spend_energy(aid, body.get("amount", 50))
            self._json(200 if ok else 403, {"ok": ok,
                     "remaining": registry.agents.get(aid, {}).get("energy_remaining", 0)})
            return
        
        if p == "/energy/regenerate":
            amt = body.get("amount", 100) if body else 100
            registry.regenerate(aid, amt)
            self._json(200, {"remaining": registry.agents.get(aid, {}).get("energy_remaining", 0)})
            return
        
        # ── Baton endpoints ──
        
        if p.startswith("/baton/") and p.endswith("/lease"):
            # Acquire handoff lease
            parts = p[7:].replace("/lease", "").split("/")
            if len(parts) >= 2 and body:
                vessel = f"{parts[0]}/{parts[1]}"
                baton_reg = load_json(BATON_REGISTRY_FILE, {"vessels": {}})
                existing = baton_reg.get("vessels", {}).get(vessel, {})
                active_lease = existing.get("active_lease")
                if active_lease and time.time() < active_lease.get("expires", 0):
                    self._json(409, {"error": "lease held", "holder": active_lease.get("agent")})
                    return
                lease = {
                    "lease_id": hashlib.sha256(f"{vessel}:{time.time()}".encode()).hexdigest()[:16],
                    "agent": body.get("agent", aid),
                    "generation": body.get("generation", 0),
                    "acquired": ts_now(),
                    "expires": time.time() + 300,  # 5 min
                }
                baton_reg.setdefault("vessels", {})[vessel] = {**existing, "active_lease": lease}
                save_json(BATON_REGISTRY_FILE, baton_reg)
                audit(f"BATON_LEASE {vessel} agent={aid}")
                self._json(200, lease)
            return
        
        if p.startswith("/baton/") and p.endswith("/commit"):
            # Commit handoff, release lease
            parts = p[7:].replace("/commit", "").split("/")
            if len(parts) >= 2 and body:
                vessel = f"{parts[0]}/{parts[1]}"
                baton_reg = load_json(BATON_REGISTRY_FILE, {"vessels": {}})
                vessel_data = baton_reg.get("vessels", {}).get(vessel, {})
                gen = body.get("generation", 0)
                score = body.get("score", 0)
                vessel_data.update({
                    "generation": gen,
                    "last_handoff": ts_now(),
                    "last_score": score,
                    "active_lease": None,
                    "history": vessel_data.get("history", []) + [{"generation": gen, "score": score, "timestamp": ts_now()}],
                })
                baton_reg["vessels"][vessel] = vessel_data
                save_json(BATON_REGISTRY_FILE, baton_reg)
                audit(f"BATON_COMMIT {vessel} gen={gen} score={score}")
                self._json(200, {"status": "committed", "generation": gen})
            return
        
        if p.startswith("/baton/") and p.endswith("/score"):
            # Score a handoff letter
            if body and body.get("letter"):
                letter = body["letter"]
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
                self._json(200, {"scores": scores, "average": avg, "passes": passes, "word_count": words})
            return
        
        self._json(404, {"error": f"unknown: {p}"})
    
    def log_message(self, *args: Any) -> None:
        pass


# ── Main ──

def main() -> None:
    port = KEEPER_PORT
    host = KEEPER_HOST
    if "--docker" in sys.argv:
        host = "0.0.0.0"
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    
    if not GITHUB_TOKEN:
        print("Error: GITHUB_TOKEN required"); sys.exit(1)
    
    server = HTTPServer((host, port), KeeperHandler)
    
    # Start health monitor in background thread
    health_thread = threading.Thread(target=health.run_forever, daemon=True)
    health_thread.start()
    
    print(f"🏪 Lighthouse Keeper v2.1 (Baton Native)")
    print(f"   HTTP: http://{host}:{port}")
    print(f"   Dashboard: http://{host}:{port}/fleet/dashboard")
    print(f"   Health: {AGENTS_PER_TICK} vessels / {HEALTH_CHECK_INTERVAL}s tick")
    print(f"   Alert: {MISSED_BEFORE_ALERT} missed | Reboot: {MISSED_BEFORE_REBOOT} missed")
    print(f"   GitHub org: {GITHUB_ORG}")
    print(f"   Ready.")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        health.stop()
        print("\n   Keeper shutting down.")
        server.server_close()

if __name__ == "__main__":
    main()
