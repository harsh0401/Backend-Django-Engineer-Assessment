import pytest
import requests

from geo.providers import (
    GeocodingProviderError,
    NominatimProvider,
    OpenRouteServiceGeocodingProvider,
    ResolvedLocation,
    get_geocoding_provider,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            response._content = b'{"error":{"code":2010,"message":"API key lacks access"}}'
            raise requests.HTTPError(f"HTTP {self.status_code}", response=response)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload, self.status_code)


def test_nominatim_waits_for_shared_request_slot(monkeypatch):
    slot_attempts = iter([False, True])
    sleeps = []
    monkeypatch.setattr("geo.providers.cache.add", lambda *args, **kwargs: next(slot_attempts))
    monkeypatch.setattr("geo.providers.time.sleep", sleeps.append)
    session = FakeSession(
        [
            {
                "address": {"country_code": "us", "ISO3166-2-lvl4": "US-TX"},
                "lat": "30.2672",
                "lon": "-97.7431",
                "display_name": "Austin, TX",
            }
        ]
    )

    result = NominatimProvider("fuel-planner/1.0 (contact: operator@example.com)", session).geocode(
        "Austin, TX"
    )

    assert result == ResolvedLocation(30.2672, -97.7431, "TX", "Austin, TX")
    assert sleeps == [0.05]
    assert session.calls[0][1]["headers"]["User-Agent"].startswith("fuel-planner/")


def test_ors_geocode_returns_us_coordinates_and_state():
    session = FakeSession(
        {
            "features": [
                {
                    "geometry": {"coordinates": [-97.7431, 30.2672]},
                    "properties": {"region_a": "TX", "country_a": "USA", "label": "Austin, TX"},
                }
            ]
        }
    )
    provider = OpenRouteServiceGeocodingProvider("test-key", session)
    result = provider.geocode("Austin, TX, USA")
    assert result == ResolvedLocation(30.2672, -97.7431, "TX", "Austin, TX")
    assert session.calls[0][1]["params"]["boundary.country"] == "USA"
    assert session.calls[0][1]["headers"]["Authorization"] == "test-key"


def test_ors_reverse_geocode_and_non_us_state_rejection():
    session = FakeSession(
        {
            "features": [
                {
                    "geometry": {"coordinates": [-96.8, 32.8]},
                    "properties": {"region": "Texas", "label": "Dallas, TX"},
                }
            ]
        }
    )
    provider = OpenRouteServiceGeocodingProvider("test-key", session)
    assert provider.reverse(32.8, -96.8).state == "TX"
    assert session.calls[0][1]["params"]["point.lat"] == 32.8

    session.payload["features"][0]["properties"]["region"] = "Ontario"
    assert provider.geocode("Toronto, Canada") is None


def test_ors_provider_requires_key_and_factory_rejects_unknown_provider():
    provider = OpenRouteServiceGeocodingProvider("")
    with pytest.raises(RuntimeError, match="ORS_API_KEY"):
        provider.geocode("Austin, TX")
    with pytest.raises(ValueError, match="ORS_API_KEY"):
        get_geocoding_provider("ors", "", "")
    with pytest.raises(ValueError, match="Unsupported GEOCODING_PROVIDER"):
        get_geocoding_provider("unknown", "", "")


def test_ors_geocoding_preserves_authorization_status():
    provider = OpenRouteServiceGeocodingProvider("test-key", FakeSession({}, 403))
    with pytest.raises(GeocodingProviderError) as error:
        provider.geocode("Austin, TX")
    assert error.value.status_code == 403
    assert "API key lacks access" in str(error.value)
    assert "test-key" not in str(error.value)