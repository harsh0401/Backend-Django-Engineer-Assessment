# Implementation Plan

## Phase 1: Project foundation
- Create Django project, `fuel` app, `routing` and `geo` integration packages.
- Pin runtime and development dependencies; configure environment-driven settings, SQLite, cache, API schema, lint, CI, Docker, and command helpers.
- Add storage models and the initial schema migration.

## Phase 2: Domain and providers
- Implement pure route projection and fuel-purchase optimization with deterministic error reporting.
- Add routing and geocoding provider interfaces, ORS/OSRM routing, Nominatim geocoding, and cached orchestration.
- Add CSV normalization, idempotent loading, and resumable station geocoding commands.

## Phase 3: API and map
- Implement validated POST/GET planning, persisted plan retrieval, consistent errors, and a fixed Leaflet map template.
- Generate OpenAPI documentation and add the Postman collection.

## Phase 4: Verification and documentation
- Add domain, ingestion, provider, and API tests using mocks only.
- Document setup, architecture, algorithm, assumptions, data quality, tradeoffs, limitations, and operations.
- Run tests, coverage, Ruff, migrations/checks, and attempt a real Dallas-to-Denver API run when credentials and network access permit.
