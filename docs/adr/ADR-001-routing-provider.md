# ADR-001: Routing Provider

## Decision

Use OpenRouteService Directions as the configured default, requesting one driving-car GeoJSON route per uncached plan. Keep a `RoutingProvider` protocol and an OSRM public-demo implementation selectable with `ROUTING_PROVIDER=osrm`.

## Consequences

ORS supplies distance, duration, and route geometry in one request but requires an API key and is quota-limited. OSRM avoids a key for evaluation but its public demo has no production SLA or guaranteed availability. The selected provider is not called again while its rounded-coordinate response is cached.