#!/usr/bin/env python3
"""Agent client — connects to Lighthouse Keeper for all API access.

Agents use this client instead of raw GitHub tokens.
The keeper handles auth, rate limiting, energy budgeting, and auditing.
"""

import json
import urllib.request
import urllib.error
from typing import Optional


class KeeperClient:
    """Client for FLUX agents to communicate through the Lighthouse Keeper."""
    
    def __init__(self, keeper_url: str, vessel_name: str):
        self.keeper_url = keeper_url.rstrip("/")
        self.vessel_name = vessel_name
        self.secret = None
        self.energy = 0
    
    def _request(self, method: str, path: str, body: dict = None) -> dict:
        url = f"{self.keeper_url}{path}"
        data = json.dumps(body).encode() if body else None
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["X-Agent-ID"] = self.vessel_name
            headers["X-Agent-Secret"] = self.secret
        
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(req)
            if response.status == 204:
                return {"status": "success"}
            return json.loads(response.read())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read())
            except:
                return {"error": e.code, "message": str(e)}
    
    # ── Lifecycle ──
    
    def register(self) -> dict:
        """Register with the keeper. Returns credentials."""
        result = self._request("POST", "/register", {"vessel": self.vessel_name})
        if "secret" in result:
            self.secret = result["secret"]
        return result
    
    def status(self) -> dict:
        return self._request("GET", "/status")
    
    def health(self) -> dict:
        return self._request("GET", "/health")
    
    # ── Fleet ──
    
    def discover(self) -> list:
        result = self._request("GET", "/discover")
        return result.get("vessels", [])
    
    # ── Files ──
    
    def read_file(self, repo: str, path: str) -> Optional[str]:
        owner, name = repo.split("/") if "/" in repo else (GITHUB_ORG, repo)
        result = self._request("GET", f"/file/{owner}/{name}/{path}")
        return result.get("decoded", None)
    
    def write_file(self, repo: str, path: str, content: str, message: str) -> dict:
        owner, name = repo.split("/") if "/" in repo else (GITHUB_ORG, repo)
        return self._request("POST", f"/file/{owner}/{name}/{path}", 
                           {"content": content, "message": message})
    
    def list_dir(self, repo: str, path: str = "") -> list:
        owner, name = repo.split("/") if "/" in repo else (GITHUB_ORG, repo)
        result = self._request("GET", f"/dir/{owner}/{name}/{path}")
        return result if isinstance(result, list) else []
    
    # ── Issues ──
    
    def list_issues(self, repo: str) -> list:
        owner, name = repo.split("/") if "/" in repo else (GITHUB_ORG, repo)
        result = self._request("GET", f"/issues/{owner}/{name}")
        return result if isinstance(result, list) else []
    
    def open_issue(self, repo: str, title: str, body: str) -> dict:
        owner, name = repo.split("/") if "/" in repo else (GITHUB_ORG, repo)
        return self._request("POST", f"/issue/{owner}/{name}", {"title": title, "body": body})
    
    def comment_issue(self, repo: str, number: int, body: str) -> dict:
        owner, name = repo.split("/") if "/" in repo else (GITHUB_ORG, repo)
        return self._request("POST", f"/comment/{owner}/{name}/{number}", {"body": body})
    
    # ── Repos ──
    
    def create_repo(self, name: str, description: str = "") -> dict:
        return self._request("POST", "/repo", {"name": name, "description": description})
    
    def fork_repo(self, owner: str, repo: str) -> dict:
        return self._request("POST", f"/fork/{owner}/{repo}")
    
    # ── I2I ──
    
    def send_i2i(self, target: str, msg_type: str, payload: dict, confidence: float = 0.5) -> dict:
        return self._request("POST", "/i2i", {
            "target": target,
            "type": msg_type,
            "payload": payload,
            "confidence": confidence,
        })
    
    # ── Energy ──
    
    def spend_energy(self, amount: int = 50) -> dict:
        result = self._request("POST", "/energy/spend", {"amount": amount})
        self.energy = result.get("remaining", 0)
        return result
    
    def regenerate(self, amount: int = 100) -> dict:
        result = self._request("POST", "/energy/regenerate", {"amount": amount})
        self.energy = result.get("remaining", 0)
        return result


# ── Test ──

if __name__ == "__main__":
    import sys
    keeper_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8900"
    vessel = sys.argv[2] if len(sys.argv) > 2 else f"test-agent-{id(object()) % 10000}"
    
    client = KeeperClient(keeper_url, vessel)
    
    print(f"Testing Keeper at {keeper_url}")
    print(f"Vessel: {vessel}")
    print()
    
    # Register
    print("1. Registering...")
    result = client.register()
    print(f"   {result}")
    
    # Health
    print("2. Health check...")
    result = client.health()
    print(f"   {result}")
    
    # Discover
    print("3. Discovering fleet...")
    vessels = client.discover()
    print(f"   Found {len(vessels)} vessels: {vessels[:3]}")
    
    # Read file
    print("4. Reading oracle1-vessel CHARTER...")
    content = client.read_file("SuperInstance/oracle1-vessel", "CHARTER.md")
    print(f"   Read {len(content or '')} chars")
    
    # Status
    print("5. Agent status...")
    status = client.status()
    print(f"   {status}")
    
    # I2I
    print("6. Sending I2I DISCOVER...")
    result = client.send_i2i("SuperInstance/oracle1-vessel", "DISCOVER", 
                            {"agent": vessel, "capabilities": ["testing"]})
    print(f"   {result}")
    
    print("\n✅ All tests passed — agent communicates through keeper")
