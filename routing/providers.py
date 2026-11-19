from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Route:
    coordinates: list[list[float]]
    distance_meters: float
    duration_seconds: float


class RoutingProvider(Protocol):
    def directions(self, start: tuple[float, float], finish: tuple[float, float]) -> Route: ...


class OpenRouteServiceProvider:
    endpoint = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()

    def directions(self, start: tuple[float, float], finish: tuple[float, float]) -> Route:
        if not self.api_key:
            raise ProviderError("OpenRouteService API key is not configured")
        try:
            response = self.session.post(
                self.endpoint,
                headers={"Authorization": self.api_key, "Content-Type": "application/json"},
                json={"coordinates": [list(start), list(finish)]},
                timeout=30,
            )
            response.raise_for_status()
            feature = response.json()["features"][0]
            summary = feature["properties"]["summary"]
            return Route(
                feature["geometry"]["coordinates"], summary["distance"], summary["duration"]
            )
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError(f"OpenRouteService route failed: {error}") from error


class OsrmProvider:
    endpoint = "https://router.project-osrm.org/route/v1/driving"

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()

    def directions(self, start: tuple[float, float], finish: tuple[float, float]) -> Route:
        url = f"{self.endpoint}/{start[0]},{start[1]};{finish[0]},{finish[1]}"
        try:
            response = self.session.get(
                url, params={"overview": "full", "geometries": "geojson"}, timeout=30
            )
            response.raise_for_status()
            route = response.json()["routes"][0]
            return Route(route["geometry"]["coordinates"], route["distance"], route["duration"])
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderError(f"OSRM route failed: {error}") from error
