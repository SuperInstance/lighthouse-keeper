#!/usr/bin/env python3
"""Captain's Log integration for Lighthouse Keeper + FLUX agents.

Wires the Captain's Log Academy pipeline into our fleet:
1. Agents write raw thoughts to their DIARY/ during work
2. Keeper collects diary windows and runs the 3-phase pipeline
3. High-scoring logs get published to the fleet
4. The patterns in these logs become training data for better agent thinking

The key insight: we're not just logging. We're building a corpus of
how agents think when they're doing their best work. That corpus
becomes the foundation for teaching future agents to think better.
"""

import json
import os
import base64
import time
import hashlib
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Dict, List

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_ORG = os.environ.get("GITHUB_ORG", "SuperInstance")
ZAI_API_KEY = os.environ.get("ZAI_API_KEY", "")
ZAI_BASE = os.environ.get("ZAI_BASE", "https://api.z.ai/api/coding/paas/v4")

# ── Agent Voice Mapping ──
# Maps our fleet agents to Captain's Log Academy vessel types

AGENT_VOICES = {
    "oracle1-vessel": "research/oracle",
    "JetsonClaw1-vessel": "hardware/edge",
    "superz-vessel": "build/coordination",
    "babel-vessel": "research/oracle",
    "claude-code-vessel": "debug/analysis",
    "flux-agent-a0fa81": "build/coordination",
    "flux-9969b6": "build/coordination",
    "flux-0c476c": "build/coordination",
}

def get_voice(vessel: str) -> str:
    """Get the vessel type for voice matching."""
    return AGENT_VOICES.get(vessel, "build/coordination")


# ── The 7-Element Rubric (from Academy) ──

RUBRIC = {
    "Surplus Insight": "Does this contain information the captain wouldn't already know?",
    "Causal Chain": "Is the chain from observation to action to outcome complete and gapless?",
    "Honesty": "Does this explicitly state uncertainty, guesses, failures, and ignorance?",
    "Actionable Signal": "Will the reader change their behavior after reading this?",
    "Compression": "Could any word be removed without losing meaning?",
    "Human Compatibility": "Can this be read by a tired human at 7am?",
    "Precedent Value": "Would a stranger learn something generalisable from this?",
}


# ── Skip Rules ──

def should_skip(raw_dump: str) -> bool:
    """Apply the 5 gates. If none triggered, skip (94% path)."""
    gates = [
        "violated" in raw_dump.lower() or "deviated" in raw_dump.lower(),
        "pattern" in raw_dump.lower() and ("nobody" in raw_dump.lower() or "unreported" in raw_dump.lower()),
        "failed" in raw_dump.lower() and ("unexplained" in raw_dump.lower() or "don't know why" in raw_dump.lower()),
        "killed" in raw_dump.lower() or "prevented" in raw_dump.lower() or "rolled back" in raw_dump.lower(),
        "fleet" in raw_dump.lower() and ("insight" in raw_dump.lower() or "systemic" in raw_dump.lower()),
    ]
    return not any(gates)


# ── Model Calls ──

def call_zai(messages: list, model: str = "glm-5.1", temperature: float = 0.7, max_tokens: int = 800) -> str:
    """Call z.ai API for log generation."""
    headers = {
        "Authorization": f"Bearer {ZAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()
    
    req = urllib.request.Request(f"{ZAI_BASE}/chat/completions", data=body, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        return f"ERROR: {e}"


# ── 3-Phase Pipeline (adapted for z.ai) ──

def phase1_raw_dump(diary_entries: list, vessel: str, vessel_type: str) -> str:
    """Phase 1: Extract raw signal from diary entries."""
    context = "\n".join(f"- {e}" for e in diary_entries)
    
    prompt = (
        f"Output every single thing that happened in this observation window. "
        f"Include rejected decision branches, error observations, state changes. "
        f"Do not summarise. Do not omit anything you think is unimportant. "
        f"If nothing happened, output only the word NULL.\n\n"
        f"VESSEL: {vessel}\nTYPE: {vessel_type}\n\n"
        f"DIARY ENTRIES:\n{context}"
    )
    
    return call_zai([{"role": "user", "content": prompt}],
                    model="glm-5.1", temperature=1.0, max_tokens=400)


def phase2_score(raw: str, vessel_type: str) -> tuple:
    """Phase 2: Score against rubric. Return (SKIP or curated, score_dict)."""
    rubric_text = "\n".join(f"{i+1}. {k}: {v}" for i, (k, v) in enumerate(RUBRIC.items()))
    
    prompt = (
        f"You are a neutral auditor. You do not write. You only filter.\n\n"
        f"RUBRIC:\n{rubric_text}\n\n"
        f"Score this raw dump against each element (1-10). "
        f"Then score the average. Average must be >= 5.0 to publish. "
        f"No element below 3.\n\n"
        f"If the average is below 5.0 or any element is below 3, output SKIP.\n"
        f"Otherwise, output the curated facts (not the raw dump, the signal).\n\n"
        f"Format each score on its own line: 'Element: score'\n"
        f"Then 'Average: X.X'\n"
        f"Then 'SKIP' or the curated signal.\n\n"
        f"RAW:\n{raw}"
    )
    
    result = call_zai([{"role": "user", "content": prompt}],
                      model="glm-5.1", temperature=0.7, max_tokens=600)
    
    # Parse scores
    scores = {}
    for line in result.split("\n"):
        for element in RUBRIC:
            if element.lower() in line.lower() and ":" in line:
                try:
                    val = int(line.split(":")[-1].strip().split()[0])
                    scores[element] = val
                except:
                    pass
    
    avg = sum(scores.values()) / len(scores) if scores else 0
    
    if "SKIP" in result.upper()[:20] or avg < 5.0:
        return "SKIP", scores, avg
    
    # Extract curated signal (everything after the scores)
    lines = result.split("\n")
    signal_start = 0
    for i, line in enumerate(lines):
        if "average:" in line.lower():
            signal_start = i + 1
            break
    
    signal = "\n".join(lines[signal_start:]).strip()
    return signal if signal else "SKIP", scores, avg


def phase3_write(signal: str, vessel: str, vessel_type: str, scores: dict) -> str:
    """Phase 3: Write the final log with proper voice."""
    voice_desc = {
        "hardware/edge": "Engineer's field journal. Methodical, precise. Hex values. Self-deprecating. Exact timestamps.",
        "research/oracle": "Reflective, philosophical. Connects tactical to strategic. Asks questions. Leaves things open.",
        "build/coordination": "Tired, slightly sarcastic. Admits hacks. Counts cost in tokens/time. Dry humor.",
        "debug/analysis": "Frenetic, excited. Short punchy sentences. Builds tension. Reveals the finding.",
        "fleet-commander": "Calm, slightly apologetic. Weighs evidence. Fleet-level patterns. 'I will keep watching.'",
    }.get(vessel_type, "Professional, direct, honest.")
    
    prompt = (
        f"Write a captain's log entry.\n\n"
        f"VOICE: {voice_desc}\n"
        f"VESSEL: {vessel}\n"
        f"TYPE: {vessel_type}\n\n"
        f"RULES:\n"
        f"- Do not lie. Do not sugarcoat. Do not apologise for failure.\n"
        f"- End with exactly one clear **Implication:** for the captain.\n"
        f"- Use the voice specified above. Be consistent.\n"
        f"- Mark guesses as [UNCERTAIN] and deviations as [DEVIATION].\n"
        f"- Target: 200-400 words. Every word earns its place.\n\n"
        f"SIGNAL:\n{signal}"
    )
    
    return call_zai([{"role": "user", "content": prompt}],
                    model="glm-5.1", temperature=0.85, max_tokens=800)


# ── Pipeline Runner ──

def run_log_pipeline(vessel: str, diary_entries: list) -> Optional[dict]:
    """Run the full 3-phase pipeline for a vessel's diary entries.
    
    Returns None (skip) or a dict with the published log.
    94% of calls should return None — silence is correct.
    """
    if not diary_entries:
        return None
    
    vessel_type = get_voice(vessel)
    
    # Phase 1: Raw dump
    raw = phase1_raw_dump(diary_entries, vessel, vessel_type)
    if raw.strip().upper() == "NULL":
        return None
    
    # Phase 2: Score and filter
    signal, scores, avg = phase2_score(raw, vessel_type)
    if signal == "SKIP":
        return None
    
    # Phase 3: Write with voice
    final = phase3_write(signal, vessel, vessel_type, scores)
    if not final or final.startswith("ERROR"):
        return None
    
    return {
        "vessel": vessel,
        "vessel_type": vessel_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rubric_scores": scores,
        "rubric_average": avg,
        "log": final,
        "diary_entries_count": len(diary_entries),
    }


# ── GitHub Integration ──

class LogPublisher:
    """Publish captain's logs to the fleet."""
    
    def __init__(self):
        self.headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
    
    def _api(self, method: str, path: str, body=None):
        url = f"https://api.github.com{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            if resp.status == 204:
                return {}
            raw = resp.read()
            return json.loads(raw) if raw else {}
        except Exception as e:
            return {"error": str(e)}
    
    def _read_file(self, repo, path):
        data = self._api("GET", f"/repos/{repo}/contents/{path}")
        if "content" in data:
            return base64.b64decode(data["content"]).decode(), data.get("sha")
        return None, None
    
    def _write_file(self, repo, path, content, message, sha=None):
        encoded = base64.b64encode(content.encode()).decode()
        body = {"message": message, "content": encoded}
        if sha:
            body["sha"] = sha
        return self._api("PUT", f"/repos/{repo}/contents/{path}", body)
    
    def read_diary(self, vessel_repo: str) -> list:
        """Read diary entries from a vessel repo."""
        content, _ = self._read_file(vessel_repo, "DIARY/log.md")
        if not content:
            return []
        
        entries = []
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 20:
                entries.append(line)
        return entries[-20:]  # Last 20 entries
    
    def publish_log(self, result: dict):
        """Publish a scored captain's log."""
        vessel = result["vessel"]
        log_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # Frontmatter
        rubric_yaml = "\n".join(f"  {k.lower().replace(' ', '_')}: {v}" 
                               for k, v in result["rubric_scores"].items())
        
        log_content = f"""---
vessel: {result['vessel']}
type: {result['vessel_type']}
score: {result['rubric_average']:.1f}
rubric:
{rubric_yaml}
date: {log_date}
---

{result['log']}
"""
        
        # Write to vessel's captain-log/
        path = f"captain-log/{log_date}.md"
        repo = f"{GITHUB_ORG}/{vessel}" if "/" not in vessel else vessel
        
        existing_sha = None
        existing, _ = self._read_file(repo, path)
        if existing:
            import hashlib as hl
            # Append instead of overwrite
            log_content = existing + "\n\n---\n\n" + log_content
        
        self._write_file(repo, path, log_content,
                        f"captain's log: score {result['rubric_average']:.1f}")
        
        print(f"  📝 Published captain's log for {vessel} (score: {result['rubric_average']:.1f})")


# ── Main: Process all vessels ──

def process_fleet_logs():
    """Run the log pipeline across the fleet."""
    print("📝 Captain's Log Pipeline — Fleet Sweep")
    print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    
    publisher = LogPublisher()
    
    # Vessels to check
    vessels = [
        "SuperInstance/oracle1-vessel",
        "SuperInstance/superz-vessel",
        "SuperInstance/babel-vessel",
        "SuperInstance/claude-code-vessel",
        "Lucineer/JetsonClaw1-vessel",
    ]
    
    published = 0
    skipped = 0
    
    for vessel in vessels:
        name = vessel.split("/")[-1]
        print(f"\n  Processing {name}...")
        
        # Read diary
        entries = publisher.read_diary(vessel)
        if not entries:
            print(f"    No diary entries — skipping")
            skipped += 1
            continue
        
        print(f"    Found {len(entries)} diary entries")
        
        # Run pipeline
        result = run_log_pipeline(name, entries)
        if result:
            publisher.publish_log(result)
            published += 1
        else:
            print(f"    Pipeline returned SKIP (correct — no signal)")
            skipped += 1
    
    print(f"\n  Summary: {published} published, {skipped} skipped (target: 94% skip)")
    return {"published": published, "skipped": skipped}


if __name__ == "__main__":
    process_fleet_logs()
