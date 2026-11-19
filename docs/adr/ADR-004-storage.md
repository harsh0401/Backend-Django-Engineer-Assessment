# ADR-004: Storage

## Decision

Use SQLite for assignment deployment, Django models for stations, geocode cache, and computed plans, and latitude/longitude indexes plus an indexed state column. Route corridor candidate retrieval uses a SQL bounding box before vectorized NumPy projection.

## Consequences

This keeps setup light and the repository portable. SQLite's geographic filtering is limited; high-volume production should move station search to PostGIS and use a Redis cache. The repository boundary keeps this migration localized.