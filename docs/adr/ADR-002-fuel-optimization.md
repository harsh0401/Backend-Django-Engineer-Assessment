# ADR-002: Fuel Optimization

## Decision

Use a pure-Python dynamic program over route-ordered stations and cumulative purchase ticks. A purchase tick is 0.5 gallons. Fuel consumption between arbitrary mile markers remains fractional and is derived from cumulative route mileage, avoiding per-leg rounding. Each state stores the least cost and purchase history for a cumulative tick count; a prefix minimum reduces transitions to earlier reachable stations.

## Consequences

The solution is globally minimum-cost for the stated discrete purchase increment and tank capacity. With N corridor stations, L feasible cumulative fuel states per station (about 101 for a 50-gallon tank), and W earlier stations that can be reached, the implementation is roughly O(N x W x L), plus route projection. The greedy cheapest-next-stop rule can be locally attractive but can force expensive later purchases or poor fuel positioning; it gives up a global optimality guarantee.