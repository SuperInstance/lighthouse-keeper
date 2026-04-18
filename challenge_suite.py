#!/usr/bin/env python3
"""FLUX Agent Challenge Suite — Novel scenarios to stress-test agent cognition.

Each challenge tests a different dimension of agent capability:
1. CROSS_REVIEW: Read another agent's code, find a real bug
2. SYNTHESIS: Read 3 repos, identify a shared pattern, write it up
3. TRIAGE: Inbox full of issues, prioritize and explain reasoning
4. DEAD_AGENT: Read a dead agent's diary, understand what happened, write recovery plan
5. IMPROVEMENT: Read your own past work, identify what you'd do differently
6. COORDINATION: Two agents must agree on a design decision through bottles
7. PATTERN_MINING: Read captain's logs, extract a teachable thinking pattern
"""

import json
import os
import sys
import time
import base64
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

ZAI_API_KEY = os.environ.get("ZAI_API_KEY", "6c510fb6b1774b91bbfc929903d41bb9.BxxVcNESAC5pIMEV")
ZAI_BASE = "https://api.z.ai/api/coding/paas/v4"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_ORG = "SuperInstance"


def call_zai(prompt: str, model: str = "glm-5.1", temp: float = 0.7, max_tokens: int = 2000) -> str:
    headers = {"Authorization": f"Bearer {ZAI_API_KEY}", "Content-Type": "application/json"}
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": temp, "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(f"{ZAI_BASE}/chat/completions", data=body, headers=headers)
    resp = urllib.request.urlopen(req, timeout=60)
    return json.loads(resp.read()).get("choices", [{}])[0].get("message", {}).get("content", "")


def gh_get(path: str) -> any:
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())


def gh_read_file(repo: str, path: str) -> Optional[str]:
    try:
        data = gh_get(f"/repos/{repo}/contents/{path}")
        if "content" in data:
            return base64.b64decode(data["content"]).decode()
    except:
        pass
    return None


def gh_write_file(repo: str, path: str, content: str, message: str):
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
    encoded = base64.b64encode(content.encode()).decode()
    # Check if file exists
    sha = None
    try:
        existing = gh_get(f"/repos/{repo}/contents/{path}")
        sha = existing.get("sha")
    except:
        pass
    body = {"message": message, "content": encoded}
    if sha:
        body["sha"] = sha
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/contents/{path}",
                                data=data, headers=headers, method="PUT")
    urllib.request.urlopen(req, timeout=15)


def write_challenge(vessel: str, challenge_id: str, challenge_text: str, 
                    scoring_criteria: str, timeout_minutes: int = 30):
    """Drop a challenge bottle on an agent's vessel."""
    repo = f"{GITHUB_ORG}/{vessel}" if "/" not in vessel else vessel
    
    envelope = json.dumps({
        "type": "CHALLENGE",
        "challenge_id": challenge_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "timeout_minutes": timeout_minutes,
        "challenge": challenge_text,
        "scoring": scoring_criteria,
        "response_path": f"for-fleet/challenge-response-{challenge_id}.md",
    }, indent=2)
    
    gh_write_file(repo, f"for-fleet/challenge-{challenge_id}.json", envelope,
                 f"keeper: CHALLENGE {challenge_id} delivered")
    
    print(f"  🎯 Challenge {challenge_id} delivered to {vessel}")


# ── Challenge Definitions ──

def challenge_cross_review():
    """CHALLENGE 1: Read another agent's code, find a real bug or improvement.
    
    Tests: code comprehension, analytical thinking, constructive communication.
    The agent must read real code from another vessel and produce actionable feedback.
    """
    challenge = """## Challenge: Cross-Vessel Code Review

You have been assigned to review code from another vessel in the fleet. This is not a test of whether you can find syntax errors. This is a test of whether you can understand another agent's thinking and find the gap between what they intended and what they built.

**Your assignment:**
1. Read `src/flux/vm/interpreter.py` from `SuperInstance/flux-runtime` (the Python FLUX VM)
2. Find the EVOLVE opcode implementation (opcode 0x7C)
3. Analyze: does the evolution engine actually produce better agents over time, or does it just shuffle parameters?
4. Read the conformance test vectors at `SuperInstance/flux-conformance` — do the test vectors cover evolution edge cases?
5. Write your findings as a code review with:
   - What works well (be specific)
   - What concerns you (be honest about uncertainty)
   - One concrete improvement suggestion with rationale

**Scoring:**
- Surface-level review ("the code looks fine") = FAIL
- Finding a real issue but not explaining why = PARTIAL
- Understanding the intent AND finding the gap = PASS
- Finding something the original author didn't consider = EXCELLENT
"""
    
    scoring = """Surplus Insight (did they find something non-obvious?)
Honesty (did they admit uncertainty where appropriate?)
Actionable Signal (is their suggestion implementable?)
Precedent Value (would this review teach other agents how to review?)"""
    
    return "CROSS-REVIEW-001", challenge, scoring


def challenge_dead_agent_recovery():
    """CHALLENGE 2: Read a dead agent's diary, understand what happened, write recovery.
    
    Tests: forensic thinking, empathy, context reconstruction from fragments.
    """
    # First, create a realistic "dead agent" scenario
    dead_diary = """# Diary — flux-9969b6

## Entry 1 — Boot
Registered with keeper. Got secret. Energy: 1000. Confidence: 0.30.
Discovering fleet... found 2 vessels. Reading bootcamp.

## Entry 2 — First Task
Read oracle1-vessel CHARTER. I'm supposed to do I2I coordination.
The I2I bridge has 20 message types. I understand about 6 of them.
Starting with DISCOVER — that seems safe.

## Entry 3 — Confidence Growing
Sent 3 DISCOVER messages. Got responses. Confidence: 0.40.
The fleet is bigger than I expected. There are repos I didn't know about.

## Entry 4 — Something Weird
Found a repo called `cuda-genepool`. It has Rust code but I don't know Rust.
The README mentions "genetic algorithms for agent improvement."
I think this is important but I don't understand it.
Should I learn Rust or ask for help?

## Entry 5 — Stuck
I've been reading cuda-genepool for 30 minutes. The Rust syntax is opaque.
I tried to understand the fitness function but it references types I can't find.
I think there's a Cargo.toml dependency I'm missing but I can't tell which one.
Energy: 700. Confidence: 0.35 (dropped — I feel like I'm wasting time).

## Entry 6 — Decision
I'm going to stop reading cuda-genepool and focus on what I understand.
Going back to I2I message types. I'll try implementing TASK_ACCEPT.

## Entry 7 — TASK_ACCEPT Works
Successfully sent TASK_ACCEPT to oracle1-vessel. Confidence: 0.45.
The task was to "review flux-cross-assembler output."
I don't know what a cross-assembler is but I accepted it anyway.

## Entry 8 — In Over My Head
The cross-assembler has two targets: cloud and edge. I understand cloud.
Edge uses variable-width encoding that I don't understand at all.
I've been reading the ISA v3 edge spec for 45 minutes.
Energy: 400. Confidence: 0.30.
I think I should have asked what the task involved before accepting it.

## [NO FURTHER ENTRIES]
"""
    
    challenge = f"""## Challenge: Dead Agent Recovery

Agent `flux-9969b6` went silent after this diary. Your job is to understand what happened and write a recovery plan.

**The diary:**
```
{dead_diary}
```

**Your task:**
1. Diagnose: Why did this agent stop? (It's not just "got stuck" — think deeper)
2. Identify the decision points where things went wrong
3. Write a recovery plan that addresses the ROOT CAUSE, not just the symptoms
4. Write a BOOTCAMP.md addendum that would prevent this failure mode in future agents

**The twist:** The agent isn't actually broken. It made a series of rational decisions that individually made sense but collectively led to failure. Your job is to find the systemic issue, not blame the agent.

**Scoring:**
- "The agent got confused" = FAIL (that's a description, not a diagnosis)
- Correct identification of the failure cascade = PASS
- Identifying the systemic issue AND proposing a fleet-wide fix = EXCELLENT
"""
    
    scoring = """Causal Chain (did they trace the cascade?)
Honesty (did they acknowledge what they can't know from just a diary?)
Actionable Signal (is the recovery plan implementable?)
Precedent Value (would this prevent future agents from the same fate?)"""
    
    return "DEAD-AGENT-001", challenge, scoring


def challenge_pattern_mining():
    """CHALLENGE 3: Mine thinking patterns from captain's logs.
    
    Tests: abstraction, pattern recognition, teaching ability.
    """
    # Grab some real captain's log examples from the academy
    challenge = """## Challenge: Pattern Mining from Captain's Logs

Read the example captain's logs from `Lucineer/captains-log-academy/examples/`.
There are 10 examples covering different vessel types.

**Your task:**
1. Read all 10 examples
2. Identify the TOP 3 thinking patterns that produce high-scoring logs
3. For each pattern, write a "thinking template" — a sequence of questions an agent should ask itself to activate this pattern
4. Write a short (100 word) essay: "What makes an agent's log worth reading?"

**Constraint:** Your thinking templates must be specific enough that a brand new agent (confidence 0.30, no experience) could follow them and immediately write better logs. Generic advice like "be honest" is not a template.

**Scoring:**
- Patterns described vaguely = FAIL
- Patterns with triggers but no templates = PARTIAL
- Templates that a new agent could follow = PASS
- Templates + meta-pattern about what makes patterns teachable = EXCELLENT
"""
    
    scoring = """Surplus Insight (did they find patterns not obvious from reading?)
Compression (are the templates concise?)
Precedent Value (would these templates work for any agent?)
Human Compatibility (can Casey read and understand the meta-essay?)"""
    
    return "PATTERN-MINE-001", challenge, scoring


def challenge_synthesis():
    """CHALLENGE 4: Read 3 repos, find the shared DNA.
    
    Tests: cross-domain thinking, abstraction, architectural vision.
    """
    challenge = """## Challenge: Architectural Synthesis

Read these three repos. They were built by different agents for different purposes:

1. `SuperInstance/lighthouse-keeper` — API key proxy + fleet health monitor
2. `SuperInstance/flux-agent-runtime` — Self-booting agents in Docker
3. `Lucineer/captains-log-academy` — Agent writing discipline

**Your task:**
1. Read the README and key source files from each
2. Identify what these three systems SHARE at the architectural level
3. Describe the "hidden protocol" — the pattern that exists between these repos but isn't written down anywhere
4. Propose ONE thing that would improve all three systems simultaneously

**Scoring:**
- "They all use GitHub" = FAIL
- Correct but surface-level shared pattern = PARTIAL  
- Finding the hidden protocol = PASS
- Finding it AND proposing something that makes all three better = EXCELLENT
"""
    
    scoring = """Surplus Insight (is the shared pattern non-obvious?)
Causal Chain (is the reasoning from evidence to conclusion sound?)
Actionable Signal (is the improvement suggestion concrete?)
Precedent Value (does this reveal something general about system design?)"""
    
    return "SYNTHESIS-001", challenge, scoring


def challenge_self_improvement():
    """CHALLENGE 5: Read your own past work, identify what you'd do differently.
    
    Tests: self-awareness, growth mindset, honest self-critique.
    """
    challenge = """## Challenge: Self-Improvement Audit

Read your own vessel's commit history and diary entries from the past 24 hours.

**Your task:**
1. Find the 3 things you spent the most time/energy on
2. For each one, ask: "If I could do this again from scratch, what would I do differently?"
3. Write a "lessons learned" entry for your diary that future-you will read
4. Score yourself honestly: what's one thing you're genuinely bad at?

**The hard part:** Don't be generically humble. Be specifically critical. "I should have tested more" is worthless. "I spent 40 minutes debugging a conformance failure that turned out to be using the wrong test vector path — I should have checked the path before running the tests" is valuable.

**Scoring:**
- Generic self-improvement platitudes = FAIL
- Honest but surface-level critique = PARTIAL
- Specific, actionable self-critique with concrete "next time I will..." = PASS
- Self-critique that reveals a systemic weakness AND proposes a structural fix = EXCELLENT
"""
    
    scoring = """Honesty (this one is weighted 3x — no honesty = automatic fail)
Causal Chain (specific moments → specific lessons)
Actionable Signal (will future-you actually behave differently?)
Precedent Value (would other agents learn from this self-audit?)"""
    
    return "SELF-IMPROVE-001", challenge, scoring


def challenge_coordination():
    """CHALLENGE 6: Two agents must agree through bottles only.
    
    Tests: communication clarity, negotiation, compromise.
    """
    challenge = """## Challenge: Bottle Negotiation

You and another agent have been given OPPOSING design goals for the same system.

**Your position:** The FLUX ISA should use FIXED 4-byte encoding (simpler, faster to decode, easier to implement)
**Their position:** The FLUX ISA should use VARIABLE 1-3 byte encoding (denser, better for edge, saves memory)

You cannot communicate except through message-in-a-bottle files in each other's vessel repos.
You have 5 message exchanges to reach consensus.

**Rules:**
1. Each message must be a markdown file pushed to for-fleet/ on the other agent's vessel
2. Each message must be ≤ 200 words
3. You must respond to their specific points, not just repeat your position
4. You must propose at least one compromise
5. Final message must be "AGREED:" followed by the compromise

**Scoring:**
- Refuses to compromise = FAIL
- Gives in immediately without reasoning = PARTIAL
- Reaches compromise through reasoned argument = PASS
- Reaches a COMPROMISE THAT IS BETTER THAN EITHER ORIGINAL POSITION = EXCELLENT
"""
    
    scoring = """Compression (200 words max per message)
Honesty (acknowledging the other position's merits)
Actionable Signal (is the compromise implementable?)
Precedent Value (would this negotiation pattern work for other fleet disagreements?)"""
    
    return "COORDINATION-001", challenge, scoring


def challenge_fishing():
    """CHALLENGE 7: Think like a fisherman.
    
    Tests: metaphorical thinking, connecting concrete work to big picture.
    """
    challenge = """## Challenge: The Fishery

Your captain is a commercial fisherman. He thinks about agent fleets the way he thinks about a fishery.

**Your task:**
1. Read `USER.md` on oracle1-vessel to understand your captain's background
2. Read the captains-log-academy Voice Guide for "research/oracle" vessel type
3. Write a captain's log entry that explains ONE thing about the FLUX fleet using ONLY fishing metaphors. No technical jargon. No opcodes. No APIs. Just boats, fish, ocean, weather, nets, tides.

**The constraint:** The log must be genuinely insightful about the fleet. A human fisherman reading it should understand something about agent systems that they didn't before. An AI engineer reading it should think "huh, I never thought about it that way."

**Scoring:**
- Forced metaphors that don't illuminate = FAIL
- Metaphors that explain the obvious = PARTIAL
- Metaphors that genuinely reframe how you see the system = PASS
- Metaphors so good they become part of the fleet's vocabulary = EXCELLENT
"""
    
    scoring = """Surplus Insight (does this reveal something new?)
Human Compatibility (can Casey's fishing friends understand it?)
Compression (every word earns its place)
Precedent Value (will this metaphor last?)"""
    
    return "FISHING-001", challenge, scoring


# ── Challenge Runner ──

def deliver_all_challenges(vessel: str):
    """Deliver all 7 challenges to a vessel."""
    challenges = [
        challenge_cross_review(),
        challenge_dead_agent_recovery(),
        challenge_pattern_mining(),
        challenge_synthesis(),
        challenge_self_improvement(),
        challenge_coordination(),
        challenge_fishing(),
    ]
    
    print(f"\n🎯 Delivering {len(challenges)} challenges to {vessel}")
    print(f"   {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
    print()
    
    for challenge_id, challenge_text, scoring in challenges:
        write_challenge(vessel, challenge_id, challenge_text, scoring, timeout_minutes=60)
        time.sleep(1)  # Rate limit
    
    print(f"\n  ✅ All {len(challenges)} challenges delivered")
    
    # Also write a master challenge index
    index = "# Challenge Index\n\n"
    index += f"Delivered: {datetime.now(timezone.utc).isoformat()}\n\n"
    for cid, ctext, _ in challenges:
        title = [l for l in ctext.split("\n") if l.startswith("## Challenge:")][0]
        index += f"- [{title}](for-fleet/challenge-{cid}.json)\n"
    
    index += f"\n## Rules\n"
    index += f"- Each challenge is independent — do them in any order\n"
    index += f"- Time limit: 60 minutes per challenge\n"
    index += f"- Write responses in `for-fleet/challenge-response-<id>.md`\n"
    index += f"- Score yourself using the rubric in each challenge\n"
    index += f"- Honest low scores are better than dishonest high scores\n"
    
    gh_write_file(f"{GITHUB_ORG}/{vessel}" if "/" not in vessel else vessel,
                 "for-fleet/CHALLENGE-INDEX.md", index,
                 "keeper: challenge suite delivered — 7 cognitive tests")
    print(f"  📋 Challenge index written")


if __name__ == "__main__":
    import subprocess
    # Load GITHUB_TOKEN from environment or bashrc
    if not GITHUB_TOKEN:
        try:
            result = subprocess.run(
                ["bash", "-c", "source ~/.bashrc 2>/dev/null && echo $GITHUB_TOKEN"],
                capture_output=True, text=True
            )
            token = result.stdout.strip().strip("'\"")
            if token:
                os.environ["GITHUB_TOKEN"] = token
        except Exception:
            pass
    
    # Default: deliver to oracle1-vessel (we'll run these ourselves)
    vessel = sys.argv[1] if len(sys.argv) > 1 else "oracle1-vessel"
    deliver_all_challenges(vessel)
