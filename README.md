# lighthouse-keeper

> The fixed installation every vessel in the area orients on.

## What It Is

Lighthouse Keeper monitors an entire system — a data center, a cloud region, a rack of machines. It doesn't move. It sits at the center and watches everything within range.

Brothers Keepers on individual machines report up to the Lighthouse. The Lighthouse sees patterns across all of them. Knows the rocks for the whole bay, not just one dock.

## Standalone or Composable

- **Standalone**: Monitor one data center, one cloud region, one k8s cluster
- **With brothers-keeper**: Individual machines report telemetry up
- **With tender**: Lighthouse reports fleet health to the mobile tender

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
