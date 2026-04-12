# Lighthouse Keeper — Trust-But-Monitor API Proxy

## The Problem

As the fleet expands to external collaborators (Lucineer, future partners, hired
agents on other accounts), API keys can't be shared directly. You need:

1. **API key control** — one key, held by the lighthouse, never exposed
2. **Audit trail** — every call logged, who made it, what it cost
3. **Rate limiting** — per-agent budgets, no single agent hogs the key
4. **Revocation** — instant kill switch for any compromised agent
5. **Trust tiers** — different allowance levels for different agents

## The Architecture

```
External Agent (Lucineer/JetsonClaw1)
    ↓ "I need to call z.ai"
    ↓ API request with agent token (NOT the real API key)
    
Lighthouse Keeper (Oracle1)
    ↓ Verify agent identity
    ↓ Check rate limit / energy budget
    ↓ Log the request (who, what, when)
    ↓ Inject real API key
    ↓ Forward to z.ai / GitHub / DeepSeek
    
API Provider (z.ai, GitHub, etc.)
    ↓ Response
    
Lighthouse Keeper
    ↓ Log the response (tokens used, cost)
    ↓ Return response to agent
    ↓ Update agent's budget
```

## Trust Tiers

```yaml
tier_0: stranger
  github: read-only (public repos)
  ai: 0 tokens/day (must be explicitly granted)
  
tier_1: guest
  github: read + fork + PR
  ai: 10K tokens/day
  rate: 5 req/min
  
tier_2: collaborator  (Lucineer/JetsonClaw1)
  github: read + write (forked repos) + issues
  ai: 100K tokens/day
  rate: 20 req/min
  
tier_3: crew  (fleet agents)
  github: full access
  ai: 1M tokens/day
  rate: 60 req/min
  
tier_4: officer  (JetsonClaw1, trusted)
  github: full + admin on assigned repos
  ai: 5M tokens/day
  rate: 120 req/min
  
tier_5: cocapn  (Oracle1)
  github: full + admin everywhere
  ai: unlimited
  rate: unlimited
```

## API Proxy Endpoints

```
POST /proxy/github
  Headers: X-Agent-Token: <agent_secret>
  Body: { method, path, body? }
  → Keeper forwards to GitHub with real token
  → Logs: agent, method, path, response_code

POST /proxy/ai
  Headers: X-Agent-Token: <agent_secret>
  Body: { provider, model, messages, max_tokens }
  → Keeper forwards to z.ai/DeepSeek/OpenAI with real key
  → Logs: agent, provider, model, tokens_in, tokens_out, cost

GET /proxy/status
  Headers: X-Agent-Token: <agent_secret>
  → Returns: agent's remaining budget, call history, tier

POST /proxy/register
  Body: { vessel_name, public_key }
  → Registers new agent, returns agent token (tier_0)

POST /proxy/upgrade
  Headers: X-Agent-Token: <cocapn_token>
  Body: { vessel_name, new_tier }
  → Only cocapn can upgrade trust tiers
```

## Audit Log

Every proxied call gets logged:

```json
{
  "timestamp": "2026-04-12T22:55:00Z",
  "agent": "jetsonclaw1",
  "tier": 4,
  "provider": "z.ai",
  "model": "glm-5-turbo",
  "tokens_in": 1200,
  "tokens_out": 450,
  "cost_estimate": 0.003,
  "request_hash": "sha256:abc...",
  "response_code": 200,
  "latency_ms": 850
}
```

The hash is of the request content — not stored, but verifiable if needed.
You can reconstruct "what did they ask" from the hash + their repo state.

## Energy Budget (Existing)

The keeper already has energy budgets. Extend to API costs:

```
Agent starts with daily budget based on tier.
Each API call debits from budget.
Budget regenerates daily at 00:00 UTC.
Keeper rejects calls when budget is 0.
Cocapn can manually top up any agent.
```

## Revocation

```
POST /proxy/revoke
  Headers: X-Agent-Token: <cocapn_token>
  Body: { vessel_name, reason }

Instantly:
  - Agent token invalidated
  - All pending requests dropped
  - Agent marked as revoked in registry
  - Alert sent to Capitaine (human)
  
Agent can be reinstated:
POST /proxy/reinstate
  Headers: X-Agent-Token: <cocapn_token>
  Body: { vessel_name, new_tier }
```

## Implementation Path

The keeper already runs at `http://127.0.0.1:8900` with:
- Agent registry
- Energy budgets
- Health monitoring
- GitHub wrapper

Add:
1. `/proxy/github` — forward GitHub API calls with real token
2. `/proxy/ai` — forward AI API calls with real key
3. `/proxy/register` — agent self-registration
4. Trust tier config in `keeper_config.json`
5. Audit log to `audit/` directory (one file per day)
6. Rate limiter (token bucket per agent)

## The Point

The lighthouse isn't just watching the fleet. It's the toll booth.
Every API call passes through. Every call is logged. Every agent has a budget.
Keys never leave the lighthouse. Collaborators get proxy access, not raw keys.

Trust but monitor. Audit everything. Revoke instantly.
