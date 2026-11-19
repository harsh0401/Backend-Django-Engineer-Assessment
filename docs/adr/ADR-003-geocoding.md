# ADR-003: Geocoding Strategy

## Decision

Use Nominatim behind a `GeocodingProvider` protocol for request start/finish resolution and offline station geocoding. Request geocoding is cached in Django's configured cache. Station geocoding is performed only by `geocode_stations`, cached in `GeocodeCache`, and rate-limited to at most one network request per second with an application-identifying User-Agent.

## Consequences

Station address geocoding is attempted first. Failed/interstate exit addresses fall back to `City, State` and are marked `city`; unresolved results are marked `failed`. City-centroid or locality-level results cost fewer queries but can place a station several miles from its actual entrance. Cached failures allow reruns without repeatedly querying the same bad address.