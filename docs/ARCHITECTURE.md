# Lighthouse Keeper — Architecture

## Position in the Keeper Stack

```
Tender (mobile, fleet logistics)
    |
    | reports up
    v
Lighthouse Keeper (fixed, system-wide)
    |
    | receives from
    v
Brothers Keeper (per-machine)
```

## Core Responsibilities

### 1. Telemetry Aggregation
- Receive periodic reports from Brothers Keepers via HTTP/IPC
- Store time-series data (resource snapshots, events, alerts)
- Normalize across heterogeneous hardware (Jetson, x86, cloud VMs)

### 2. Pattern Detection
- Cross-machine correlation (cooling failure -> thermal throttling on multiple GPUs)
- Fleet-wide anomaly detection (all agents idle simultaneously)
- Trend analysis (memory leak across 3 nodes over 2 weeks)

### 3. Fleet Health Scoring
- Per-machine green/yellow/red status
- Aggregate fleet score
- Historical comparison (this week vs last week)

### 4. Incident Routing
- Escalate brother-level alerts to appropriate responders
- Deduplication (10 brothers reporting the same network issue -> 1 incident)
- Incident timeline reconstruction

### 5. Brothers Registry
- Track which brothers are online/offline
- Auto-discovery (mDNS, consul, or manual registration)
- Brother version tracking

## Protocol: Brother -> Lighthouse

Brothers push telemetry to the lighthouse on each tick:

```json
POST /api/v1/report
{
  "brother_id": "jetson-orin-01",
  "timestamp": "2026-04-11T14:42:00Z",
  "resources": { "ram_pct": 72, "cpu_pct": 15 },
  "flywheel": { "status": "spinning", "commits_per_hour": 4 },
  "alerts": [],
  "gpu": { "mem_used_mb": 2048, "mem_total_mb": 8192 }
}
```

## Protocol: Tender -> Lighthouse

Tenders query the lighthouse for fleet status:

```json
GET /api/v1/fleet/status
{
  "region": "us-west-2",
  "machines": 12,
  "online": 11,
  "fleet_score": 0.85,
  "incidents_active": 1,
  "brothers": []
}
```

## Implementation Plan

### Phase 1: Core
- HTTP server for receiving brother reports
- In-memory fleet state
- Health scoring algorithm
- REST API for status queries
- Basic dashboard (HTML)

### Phase 2: Intelligence
- Time-series storage (SQLite or similar)
- Cross-machine pattern detection
- Incident deduplication and routing
- Brother auto-discovery

### Phase 3: Resilience
- Lighthouse high availability (primary/standby)
- Offline buffer (brothers queue reports when lighthouse is down)
- Configuration management (push config to brothers)
