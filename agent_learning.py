#!/usr/bin/env python3
"""Agent Learning Loop — Captain's Logs → Better Thinking Patterns.

The pipeline:
1. Agents write raw thoughts during work (DIARY/)
2. Captain's Log Academy scores and filters → published logs
3. Published logs are analyzed for thinking patterns
4. Patterns become "thinking templates" that agents can load
5. Templates bias agents toward proven effective thinking styles

This is the feedback loop Casey described:
  "learning how they think as they work through jobs 
   to help us improve how they think"

The corpus of captain's logs IS the training data.
Not for LoRA (yet) — for prompt engineering and skill extraction.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
import urllib.request

ZAI_API_KEY = os.environ.get("ZAI_API_KEY", "")
ZAI_BASE = os.environ.get("ZAI_BASE", "https://api.z.ai/api/coding/paas/v4")

# ── Pattern Extraction ──

def call_zai(prompt: str, model: str = "glm-5.1", temp: float = 0.7) -> str:
    headers = {"Authorization": f"Bearer {ZAI_API_KEY}", "Content-Type": "application/json"}
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": temp, "max_tokens": 1000}).encode()
    req = urllib.request.Request(f"{ZAI_BASE}/chat/completions", data=body, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read()).get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        return f"ERROR: {e}"


def extract_thinking_patterns(logs: List[str]) -> Dict:
    """Analyze a batch of captain's logs for recurring thinking patterns.
    
    Returns a dict of pattern categories with examples.
    """
    logs_text = "\n---\n".join(logs[:10])  # Max 10 logs per batch
    
    prompt = f"""Analyze these captain's logs from autonomous agents. Extract RECURRING THINKING PATTERNS.

For each pattern you find, describe:
1. The pattern name (e.g., "source-first debugging", "cost-awareness", "cross-vessel learning")
2. When this pattern activates (trigger conditions)
3. The thinking steps the agent follows
4. Why this pattern produces good logs
5. A template phrase an agent could use to activate this pattern

Focus on patterns that produced high-scoring logs. These are the thinking styles we want to teach.

LOGS:
{logs_text}

Output as JSON array of pattern objects with keys: name, trigger, steps, why_good, template_phrase"""

    result = call_zai(prompt, model="glm-5.1", temp=0.5)
    
    try:
        # Try to parse as JSON
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]
        return {"patterns": json.loads(result), "analyzed_count": len(logs)}
    except:
        return {"patterns": [], "raw_analysis": result[:500], "analyzed_count": len(logs)}


def generate_thinking_skill(patterns: List[Dict], vessel_type: str) -> str:
    """Generate a FLUX-compatible thinking skill from extracted patterns.
    
    This skill can be loaded by agents to bias their thinking toward
    proven effective patterns.
    """
    patterns_text = "\n".join(
        f"- **{p.get('name', '?')}**: {p.get('template_phrase', '')}"
        for p in patterns
    )
    
    prompt = f"""Create an AGENT.md thinking skill for vessel type '{vessel_type}'.

The skill should teach the agent to use these proven thinking patterns:
{patterns_text}

Format as AGENT.md markdown with:
1. Skill name and description
2. When to activate each pattern (triggers)
3. Step-by-step thinking templates
4. Self-check questions the agent should ask
5. Anti-patterns to avoid (from low-scoring logs)

The skill should be loadable by any agent of this vessel type.
Keep it practical — this is a training tool, not theory."""

    return call_zai(prompt, model="glm-5.1", temp=0.7)


# ── Pattern Library ──

class PatternLibrary:
    """Accumulated thinking patterns across the fleet, indexed by vessel type."""
    
    def __init__(self, path: str = "/tmp/lighthouse-keeper/pattern_library.json"):
        self.path = path
        self.library = self._load()
    
    def _load(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except:
            return {"patterns": {}, "last_updated": None, "total_logs_analyzed": 0}
    
    def _save(self):
        self.library["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(self.path, "w") as f:
            json.dump(self.library, f, indent=2)
    
    def add_patterns(self, vessel_type: str, patterns: List[Dict]):
        """Add extracted patterns for a vessel type."""
        if vessel_type not in self.library["patterns"]:
            self.library["patterns"][vessel_type] = []
        
        for p in patterns:
            self.library["patterns"][vessel_type].append({
                "name": p.get("name"),
                "trigger": p.get("trigger"),
                "steps": p.get("steps"),
                "template_phrase": p.get("template_phrase"),
                "discovered": datetime.now(timezone.utc).isoformat(),
            })
        
        self.library["total_logs_analyzed"] += len(patterns)
        self._save()
    
    def get_patterns(self, vessel_type: str) -> List[Dict]:
        """Get all known patterns for a vessel type."""
        return self.library.get("patterns", {}).get(vessel_type, [])
    
    def get_all_patterns(self) -> Dict:
        """Get the full pattern library."""
        return self.library


# ── Main: Build pattern library from published logs ──

def build_pattern_library():
    """Analyze all published captain's logs and extract thinking patterns."""
    print("🧠 Building Thinking Pattern Library")
    print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    
    library = PatternLibrary()
    
    # Mock: in production, read from fleet repos' captain-log/ directories
    # For now, use the example logs from the academy
    
    vessel_types = {
        "hardware/edge": ["JC1"],
        "research/oracle": ["ORC-3"],
        "build/coordination": ["BLD-7"],
        "debug/analysis": ["DBG-2"],
        "fleet-commander": ["CMD-0"],
    }
    
    for vtype, vessels in vessel_types.items():
        print(f"\n  Analyzing {vtype} patterns...")
        
        # In production: fetch published logs from each vessel
        # For now: extract patterns from the academy examples
        prompt = f"""What are the 3 most effective thinking patterns for vessel type '{vtype}'?

Based on the Captain's Log Academy, these patterns produce high-scoring logs:
- hardware/edge: source-first debugging, register-level precision, self-correction
- research/oracle: cross-domain connection, asking unanswerable questions, precedent-seeking  
- build/coordination: cost-counting, failure-honesty, workflow-audit
- debug/analysis: tension-building, reveal-structure, bypass-the-tool
- fleet-commander: calm-weighing, aggregate-awareness, watching-without-panicking

For each pattern, give: name, trigger, steps, template_phrase

Output as JSON array."""

        result = call_zai(prompt, temp=0.5)
        
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            patterns = json.loads(result)
            library.add_patterns(vtype, patterns)
            print(f"    Added {len(patterns)} patterns")
        except:
            print(f"    Could not parse patterns: {result[:100]}")
    
    print(f"\n  Pattern library: {library.library['total_logs_analyzed']} patterns across {len(library.library['patterns'])} vessel types")
    print(f"  Saved to {library.path}")
    
    return library


if __name__ == "__main__":
    lib = build_pattern_library()
    print(json.dumps(lib.get_all_patterns(), indent=2)[:1000])
