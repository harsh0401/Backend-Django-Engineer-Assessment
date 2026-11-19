from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import requests
from django.core.cache import cache

STATE_CODES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}
US_STATES = frozenset(STATE_CODES.values())


@dataclass(frozen=True)
class ResolvedLocation:
    latitude: float
    longitude: float
    state: str
    label: str


class GeocodingProvider(Protocol):
    def geocode(self, query: str) -> ResolvedLocation | None: ...

    def reverse(self, latitude: float, longitude: float) -> ResolvedLocation | None: ...


class GeocodingProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _wait_for_nominatim_slot() -> None:
    while not cache.add("geo:nominatim:request-slot", True, timeout=1):
        time.sleep(0.05)


def _http_error_detail(error: requests.HTTPError) -> str:
    response = error.response
    if response is None:
        return str(error)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("error", payload)
        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("description")
            code = detail.get("code")
            if message:
                return f"{message} (provider code: {code})" if code else str(message)
    text = response.text.strip()
    return text[:400] if text else str(error)


class NominatimProvider:
    geocode_url = "https://nominatim.openstreetmap.org/search"
    reverse_url = "https://nominatim.openstreetmap.org/reverse"

    def __init__(self, user_agent: str, session: requests.Session | None = None):
        if not user_agent.strip():
            raise ValueError(
                "Set NOMINATIM_USER_AGENT to a descriptive application name and contact"
            )
        self.user_agent = user_agent
        self.session = session or requests.Session()

    @staticmethod
    def _parse(item: dict) -> ResolvedLocation | None:
        address = item.get("address", {})
        if address.get("country_code", "").lower() != "us":
            return None
        state = address.get("ISO3166-2-lvl4", "").removeprefix("US-").upper()
        if state not in US_STATES:
            state = STATE_CODES.get(address.get("state", "").lower(), "")
        if state not in US_STATES:
            return None
        return ResolvedLocation(
            float(item["lat"]), float(item["lon"]), state, item.get("display_name", "")
        )

    def geocode(self, query: str) -> ResolvedLocation | None:
        try:
            _wait_for_nominatim_slot()
            response = self.session.get(
                self.geocode_url,
                params={
                    "q": query,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "countrycodes": "us",
                    "limit": 1,
                },
                headers={"User-Agent": self.user_agent},
                timeout=15,
            )
            response.raise_for_status()
            results = response.json()
            return self._parse(results[0]) if results else None
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            raise GeocodingProviderError(
                f"Nominatim geocoding failed: {_http_error_detail(error)}", status_code
            ) from error
        except (requests.RequestException, IndexError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"Nominatim geocoding failed: {error}") from error

    def reverse(self, latitude: float, longitude: float) -> ResolvedLocation | None:
        try:
            _wait_for_nominatim_slot()
            response = self.session.get(
                self.reverse_url,
                params={"lat": latitude, "lon": longitude, "format": "jsonv2", "addressdetails": 1},
                headers={"User-Agent": self.user_agent},
                timeout=15,
            )
            response.raise_for_status()
            return self._parse(response.json())
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            raise GeocodingProviderError(
                f"Nominatim reverse geocoding failed: {_http_error_detail(error)}", status_code
            ) from error
        except (requests.RequestException, KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"Nominatim reverse geocoding failed: {error}") from error


class OpenRouteServiceGeocodingProvider:
    search_url = "https://api.openrouteservice.org/geocode/search"
    reverse_url = "https://api.openrouteservice.org/geocode/reverse"

    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()

    @staticmethod
    def _parse(feature: dict) -> ResolvedLocation | None:
        properties = feature.get("properties", {})
        state = properties.get("region_a", "").removeprefix("US-").upper()
        if state not in US_STATES:
            state = STATE_CODES.get(properties.get("region", "").lower(), "")
        if state not in US_STATES:
            return None
        longitude, latitude = feature["geometry"]["coordinates"][:2]
        return ResolvedLocation(
            float(latitude),
            float(longitude),
            state,
            properties.get("label", ""),
        )

    def _get(self, url: str, params: dict) -> dict:
        if not self.api_key:
            raise RuntimeError("Set ORS_API_KEY to use OpenRouteService geocoding")
        try:
            response = self.session.get(
                url,
                params=params,
                headers={"Authorization": self.api_key},
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            raise GeocodingProviderError(
                f"OpenRouteService geocoding failed: {_http_error_detail(error)}", status_code
            ) from error
        except (requests.RequestException, TypeError, ValueError) as error:
            raise RuntimeError(f"OpenRouteService geocoding failed: {error}") from error

    def geocode(self, query: str) -> ResolvedLocation | None:
        result = self._get(
            self.search_url,
            {"text": query, "boundary.country": "USA", "size": 1},
        )
        features = result.get("features", [])
        return self._parse(features[0]) if features else None

    def reverse(self, latitude: float, longitude: float) -> ResolvedLocation | None:
        result = self._get(
            self.reverse_url,
            {
                "point.lat": latitude,
                "point.lon": longitude,
                "boundary.country": "USA",
                "size": 1,
            },
        )
        features = result.get("features", [])
        return self._parse(features[0]) if features else None


def get_geocoding_provider(name: str, api_key: str, user_agent: str) -> GeocodingProvider:
    if name == "ors":
        if not api_key:
            raise ValueError("Set ORS_API_KEY to use OpenRouteService geocoding")
        return OpenRouteServiceGeocodingProvider(api_key)
    if name == "nominatim":
        return NominatimProvider(user_agent)
    raise ValueError(f"Unsupported GEOCODING_PROVIDER: {name}")
