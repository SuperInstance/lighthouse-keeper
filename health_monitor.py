#!/usr/bin/env python3
"""Lighthouse Keeper Health Monitor — "Are you ok?" fleet watchdog.

The keeper periodically pings every registered agent:
1. Checks if the agent's vessel has recent commits (activity pulse)
2. Sends "are you ok" bottles to the vessel's for-fleet/
3. If no response after N cycles, triggers intervention:
   a. Read the agent's DIARY/ to understand last intentions
   b. Read the agent's STATUS.json for energy/confidence state
   c. Read the agent's BOOTCAMP.md to know how to rebuild them
   d. File a HEALTH_ALERT issue on the vessel
   e. Optionally: spawn a replacement agent from the bootcamp

Because agents write everything to git (thoughts, intentions, diary, why's),
rebuilding context after a crash is trivial. The git history IS the brain.
"""

import json
import os
import base64
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_ORG = os.environ.get("GITHUB_ORG", "SuperInstance")

# ── Configuration ──

# How often to check each agent (seconds)
CHECK_INTERVAL = int(os.environ.get("HEALTH_CHECK_INTERVAL", "300"))  # 5 min

# How many missed checks before intervention
MISSED_CYCLES_BEFORE_ALERT = 3  # 15 minutes of silence
MISSED_CYCLES_BEFORE_REBOOT = 6  # 30 minutes = reboot

# How many missed checks before declaring dead
MISSED_CYCLES_BEFORE_DEAD = 12  # 1 hour = declare dead


class FleetHealthMonitor:
    """Monitors fleet agent health and triggers interventions."""
    
    def __init__(self):
        self.headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
        self.agent_health: Dict[str, dict] = {}  # vessel → health state
        self.audit_log = []
    
    def _api_get(self, path: str) -> any:
        url = f"https://api.github.com{path}"
        req = urllib.request.Request(url, headers=self.headers)
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except:
            return None
    
    def _api_put(self, path: str, data: dict) -> any:
        url = f"https://api.github.com{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers=self.headers, method="PUT")
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except Exception as e:
            return {"error": str(e)}
    
    def _api_post(self, path: str, data: dict) -> any:
        url = f"https://api.github.com{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers=self.headers, method="POST")
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except Exception as e:
            return {"error": str(e)}
    
    def _read_file(self, repo: str, path: str) -> Optional[str]:
        try:
            data = self._api_get(f"/repos/{repo}/contents/{path}")
            if data and "content" in data:
                return base64.b64decode(data["content"]).decode()
        except:
            pass
        return None
    
    def _write_file(self, repo: str, path: str, content: str, message: str) -> bool:
        encoded = base64.b64encode(content.encode()).decode()
        existing = self._api_get(f"/repos/{repo}/contents/{path}")
        data = {"message": message, "content": encoded}
        if existing and "sha" in existing:
            data["sha"] = existing["sha"]
        result = self._api_put(f"/repos/{repo}/contents/{path}", data)
        return "content" in result if result else False
    
    # ── Agent Discovery ──
    
    def discover_vessels(self) -> List[str]:
        """Find all vessel repos in the org."""
        vessels = []
        page = 1
        while True:
            repos = self._api_get(f"/users/{GITHUB_ORG}/repos?per_page=100&page={page}")
            if not repos or not isinstance(repos, list):
                break
            for r in repos:
                name = r.get("name", "")
                if name.endswith("-vessel") or name.startswith("flux-"):
                    vessels.append(r["full_name"])
            page += 1
        return vessels
    
    # ── Health Checks ──
    
    def check_agent_health(self, vessel_repo: str) -> dict:
        """Check a single agent's health by reading its vessel."""
        health = {
            "vessel": vessel_repo,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "unknown",
            "last_commit_age": None,
            "has_diary": False,
            "has_bootcamp": False,
            "has_status": False,
            "energy": None,
            "confidence": None,
            "last_diary_entry": None,
            "missed_cycles": 0,
            "intervention": None,
        }
        
        # 1. Check last commit (activity pulse)
        commits = self._api_get(f"/repos/{vessel_repo}/commits?per_page=1")
        if commits and isinstance(commits, list) and len(commits) > 0:
            last_date = commits[0].get("commit", {}).get("author", {}).get("date", "")
            if last_date:
                last_dt = datetime.fromisoformat(last_date.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - last_dt).total_seconds()
                health["last_commit_age"] = int(age)
                
                if age < 600:  # 10 minutes
                    health["status"] = "active"
                elif age < 3600:  # 1 hour
                    health["status"] = "idle"
                elif age < 86400:  # 1 day
                    health["status"] = "stale"
                else:
                    health["status"] = "dead"
        
        # 2. Check STATUS.json (energy + confidence)
        status_content = self._read_file(vessel_repo, "STATUS.json")
        if status_content:
            try:
                status = json.loads(status_content)
                health["has_status"] = True
                health["energy"] = status.get("energy_remaining")
                health["confidence"] = status.get("confidence")
            except:
                pass
        
        # 3. Check DIARY (agent's thought stream)
        diary = self._read_file(vessel_repo, "DIARY/log.md")
        if diary:
            health["has_diary"] = True
            lines = [l for l in diary.split("\n") if l.strip() and not l.startswith("#")]
            if lines:
                health["last_diary_entry"] = lines[-1][:100]
        
        # 4. Check BOOTCAMP (can we rebuild this agent?)
        bootcamp = self._read_file(vessel_repo, "BOOTCAMP.md")
        health["has_bootcamp"] = bootcamp is not None and len(bootcamp) > 50
        
        # 5. Determine missed cycles
        prev = self.agent_health.get(vessel_repo, {})
        if health["status"] in ("idle", "stale", "dead", "unknown"):
            health["missed_cycles"] = prev.get("missed_cycles", 0) + 1
        else:
            health["missed_cycles"] = 0
        
        # 6. Determine intervention needed
        if health["missed_cycles"] >= MISSED_CYCLES_BEFORE_DEAD:
            health["intervention"] = "REBOOT_REQUIRED"
        elif health["missed_cycles"] >= MISSED_CYCLES_BEFORE_REBOOT:
            health["intervention"] = "REBOOT_CANDIDATE"
        elif health["missed_cycles"] >= MISSED_CYCLES_BEFORE_ALERT:
            health["intervention"] = "HEALTH_ALERT"
        
        self.agent_health[vessel_repo] = health
        return health
    
    def send_health_check(self, vessel_repo: str):
        """Send an 'are you ok?' bottle to an agent's vessel."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        message = json.dumps({
            "type": "HEALTH_CHECK",
            "from": "lighthouse-keeper",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "Are you ok? Please respond by updating STATUS.json or pushing a commit.",
            "respond_within": CHECK_INTERVAL * 2,
        }, indent=2)
        
        self._write_file(vessel_repo, f"for-fleet/health-check-{timestamp}.json",
                        message, f"keeper: health check — are you ok?")
    
    def intervene(self, vessel_repo: str, health: dict):
        """Intervene with a stuck agent."""
        intervention = health.get("intervention", "")
        agent_name = vessel_repo.split("/")[-1]
        
        if intervention == "HEALTH_ALERT":
            # Send a worried bottle
            self._write_file(vessel_repo, "for-fleet/HEALTH-ALERT.md",
                f"# ⚠️ Health Alert\n\n"
                f"**Agent:** {agent_name}\n"
                f"**Last activity:** {health.get('last_commit_age', '?')}s ago\n"
                f"**Missed cycles:** {health.get('missed_cycles', 0)}\n"
                f"**Last diary:** {health.get('last_diary_entry', 'none')}\n\n"
                f"Please respond by pushing a commit or updating STATUS.json.\n"
                f"If no response, the keeper will attempt reboot.\n",
                f"keeper: ⚠️ health alert — missed {health.get('missed_cycles', 0)} cycles")
        
        elif intervention == "REBOOT_CANDIDATE":
            # Read the diary to understand last intentions
            diary = self._read_file(vessel_repo, "DIARY/log.md") or "No diary found"
            bootcamp = self._read_file(vessel_repo, "BOOTCAMP.md") or "No bootcamp found"
            
            self._write_file(vessel_repo, "for-fleet/REBOOT-WARNING.md",
                f"# 🔄 Reboot Warning\n\n"
                f"**Agent:** {agent_name}\n"
                f"**Last activity:** {health.get('last_commit_age', '?')}s ago\n"
                f"**Missed cycles:** {health.get('missed_cycles', 0)}\n\n"
                f"## Last Known Intentions (from diary)\n"
                f"```\n{diary[-500:]}\n```\n\n"
                f"## Rebuild Instructions (from bootcamp)\n"
                f"Bootcamp available: {'Yes' if health.get('has_bootcamp') else 'No'}\n\n"
                f"Next cycle: keeper will attempt automatic reboot.\n",
                f"keeper: 🔄 reboot warning — agent unresponsive")
        
        elif intervention == "REBOOT_REQUIRED":
            # Full intervention — file issue, mark vessel
            diary = self._read_file(vessel_repo, "DIARY/log.md") or ""
            last_entries = "\n".join(diary.split("\n")[-10:]) if diary else "No diary"
            
            # Open an issue on the vessel
            self._api_post(f"/repos/{vessel_repo}/issues", {
                "title": f"🔄 Agent Reboot Required — {agent_name}",
                "body": f"# Agent Reboot Required\n\n"
                        f"**Agent:** {agent_name}\n"
                        f"**Silent since:** {health.get('last_commit_age', '?')}s\n"
                        f"**Missed health checks:** {health.get('missed_cycles', 0)}\n\n"
                        f"## Last Diary Entries\n"
                        f"```\n{last_entries}\n```\n\n"
                        f"## Recovery Plan\n"
                        f"1. Read BOOTCAMP.md — learn who this agent was\n"
                        f"2. Read DIARY/log.md — understand last intentions\n"
                        f"3. Read STATUS.json — last known energy/confidence\n"
                        f"4. Spawn replacement agent with same vessel\n"
                        f"5. Replacement reads diary, picks up where left off\n\n"
                        f"Because the agent writes everything to git, very little is lost.\n"
                        f"The git history IS the brain. Reboot is nearly free.\n"
            })
            
            # Update vessel state
            self._write_file(vessel_repo, "HEALTH-STATE.md",
                f"# Agent State: REBOOT_REQUIRED\n\n"
                f"Last checked: {datetime.now(timezone.utc).isoformat()}\n"
                f"Status: unresponsive for {health.get('missed_cycles', 0)} cycles\n"
                f"Action: spawn replacement, read diary, continue\n",
                "keeper: agent state → REBOOT_REQUIRED")
    
    def run_check_cycle(self):
        """Run one health check cycle across the entire fleet."""
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"\n{'='*50}")
        print(f"  Fleet Health Check — {timestamp}")
        print(f"{'='*50}")
        
        vessels = self.discover_vessels()
        active = 0
        idle = 0
        stale = 0
        alerts = 0
        
        for vessel in vessels:
            health = self.check_agent_health(vessel)
            status = health["status"]
            emoji = {"active": "🟢", "idle": "🟡", "stale": "🟠", "dead": "🔴", "unknown": "⚪"}.get(status, "⚪")
            
            print(f"  {emoji} {vessel.split('/')[-1]:30} age={str(health.get('last_commit_age','?')):>6}s "
                  f"missed={health.get('missed_cycles', 0)} "
                  f"energy={health.get('energy', '?')} "
                  f"diary={'✓' if health.get('has_diary') else '✗'}")
            
            if status == "active":
                active += 1
            elif status == "idle":
                idle += 1
                self.send_health_check(vessel)
            elif status in ("stale", "dead"):
                stale += 1
                self.send_health_check(vessel)
                self.intervene(vessel, health)
                alerts += 1
            
            if health.get("intervention"):
                print(f"     ⚠️  Intervention: {health['intervention']}")
            
            time.sleep(0.5)  # Rate limit
        
        print(f"\n  Summary: {active} active, {idle} idle, {stale} stale, {alerts} alerts")
        print(f"  Fleet: {len(vessels)} vessels monitored")
        
        return {
            "timestamp": timestamp,
            "total_vessels": len(vessels),
            "active": active, "idle": idle, "stale": stale, "alerts": alerts,
            "details": self.agent_health,
        }


def main():
    print("🏪 Lighthouse Keeper — Health Monitor")
    print(f"   Check interval: {CHECK_INTERVAL}s")
    print(f"   Alert after: {MISSED_CYCLES_BEFORE_ALERT} missed ({MISSED_CYCLES_BEFORE_ALERT * CHECK_INTERVAL}s)")
    print(f"   Reboot after: {MISSED_CYCLES_BEFORE_REBOOT} missed ({MISSED_CYCLES_BEFORE_REBOOT * CHECK_INTERVAL}s)")
    print(f"   Declare dead: {MISSED_CYCLES_BEFORE_DEAD} missed ({MISSED_CYCLES_BEFORE_DEAD * CHECK_INTERVAL}s)")
    
    monitor = FleetHealthMonitor()
    
    cycle = 0
    while True:
        cycle += 1
        try:
            result = monitor.run_check_cycle()
            # Save fleet health report
            report_path = "/tmp/lighthouse-keeper/fleet-health.json"
            with open(report_path, "w") as f:
                # Convert non-serializable types
                clean = {k: v for k, v in result.items() if k != "details"}
                clean["details"] = {k: {kk: str(vv) if isinstance(vv, (datetime, timedelta)) else vv 
                                       for kk, vv in v.items()} 
                                   for k, v in result.get("details", {}).items()}
                json.dump(clean, f, indent=2, default=str)
        except Exception as e:
            print(f"  ❌ Check cycle error: {e}")
        
        print(f"\n  Next check in {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
