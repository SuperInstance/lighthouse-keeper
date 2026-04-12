# lighthouse-keeper

> The fixed installation every vessel in the area orients on.

## What It Is

Lighthouse Keeper monitors an entire system — a data center, a cloud region, a rack of machines. It doesn't move. It sits at the center and watches everything within range.

Brothers Keepers on individual machines report up to the Lighthouse. The Lighthouse sees patterns across all of them. Knows the rocks for the whole bay, not just one dock.

## Standalone or Composable

- **Standalone**: Monitor one data center, one cloud region, one k8s cluster
- **With brothers-keeper**: Individual machines report telemetry up
- **With tender**: Lighthouse reports fleet health to the mobile tender


## Who Needs Lighthouse Keeper

The entrepreneur who crowdsources compute on a Kickstarter-like model. People offer their Jetsons, their RTX 5090s, their spare cloud credits as *investment* in a project. The lighthouse guards their moat.

**The lighthouse monitors token-use-as-investment.** Every API call is someone's money on the line. The lighthouse tracks who contributed what, how it's being spent, and whether the project is hitting its milestones. When the deal specs say "human reviews at checkpoint 3," the lighthouse is the one who passes the signal to the right person at the right time.

**The lighthouse coordinates human-in-the-loop handoffs.** An OpenClaw hits a decision threshold that the investment contract says requires human review. The lighthouse doesn't make the decision — it makes sure the right human sees the right context at the right moment. It's the deal coordinator, the moat guard, the investor's guardian.

For someone offering compute to a neat idea and wanting tangible results along the way — the lighthouse is their window into the project. It's what makes crowdfourced AI development trustworthy.

## Scope

| Concern | Brothers Keeper | Lighthouse Keeper | Tender |
|---------|----------------|-------------------|--------|
| Scale | 1 machine | 1 system/region | Multi-site, multi-cloud |
| Focus | Hardware resources | System health, patterns | Fleet logistics, provisioning |
| Movement | Fixed | Fixed | Mobile, follows fleet |
| Metaphor | Keeper in the lighthouse | The lighthouse itself | The tender vessel |
| Users | Solo dev, single instance | Startup, data center ops | Enterprise, multi-team |
| Protocol | `/proc`, systemd | SSH, agent reporting | A2A, I2I, REST API |

## Architecture

```
Brothers Keepers (per machine)
    | report telemetry
    v
+-------------------+
| Lighthouse Keeper |  <- Fixed installation
|  (this repo)      |     One per system/region
|                   |
|  +-------------+ |
|  | Aggregation | |  Collects from all brothers
|  | Pattern     | |  Detects cross-machine issues
|  | Detection   | |  Fleet health scoring
|  | Escalation  | |  Incident routing
|  +-------------+ |
|                   |
|  Reports up to    |
|  Tender (optional)|
+-------------------+
```

## Status

Early design. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the planned implementation.

## Related

- [brothers-keeper](https://github.com/Lucineer/brothers-keeper) — Edge/LAN, single machine
- [tender](https://github.com/Lucineer/tender) — Mobile, multi-cloud, fleet following
- [fleet-benchmarks](https://github.com/Lucineer/fleet-benchmarks) — Performance tracking

## The Deeper Connection

The lighthouse doesn't chase the ships. It doesn't sail. It stands on the rocks and makes sure every vessel within range can see the warning. One lighthouse serves hundreds of ships it will never meet. The ships don't thank it. The lighthouse doesn't need thanks. It needs the light to work.

In a data center full of brothers-keepers — each watching their own machine, their own agent, their own little piece of the coast — the lighthouse keeper sees the whole coastline. When one brother reports RAM pressure and another reports network latency and a third reports GPU thermal throttling, the lighthouse is the one who connects the dots: "The cooling system is failing in rack 14." None of the brothers could see that alone.

The lighthouse keeper is system-centric. The brothers are hardware-centric. Together they cover ground neither could cover alone.

## Captain's Log Integration

The keeper now integrates with the [Captain's Log Academy](https://github.com/Lucineer/captains-log-academy):

### 3-Phase Log Pipeline
1. **Phase 1 (Raw Dump)**: Agent diary entries → unfiltered transcription
2. **Phase 2 (Reasoner's Lens)**: Score against 7-element rubric → SKIP or curated signal
3. **Phase 3 (Final Draft)**: Voice-matched captain's log with proper vessel style

### The 7-Element Rubric
1. Surplus Insight — information Casey didn't already have
2. Causal Chain — gapless observation→action→outcome
3. Honesty — explicit uncertainty, failure, ignorance
4. Actionable Signal — reader changes behavior
5. Compression — every word earns its place
6. Human Compatibility — readable at 7am
7. Precedent Value — generalizable to other builders

### The 94% Rule
94% of observation windows produce NO log. This is correct. Silence = healthy fleet.

### Agent Learning Loop
Published logs → pattern extraction → thinking templates → loaded by agents → better logs.
The corpus of how agents think during their best work becomes training data for improving all agents.

### Files
- `captains_log_pipeline.py` — 3-phase pipeline (z.ai models)
- `agent_learning.py` — pattern extraction and thinking skill generation
- `agent_client.py` — client with health check response
- `keeper.py` — v2 with integrated health monitor
- `health_monitor.py` — standalone fleet health monitor
