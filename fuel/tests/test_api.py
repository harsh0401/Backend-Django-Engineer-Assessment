import json
import uuid

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from fuel.models import FuelPlan
from geo.providers import ResolvedLocation
from routing.providers import ProviderError, Route


class FakeGeocoder:
    def geocode(self, query):
        if query == "Dallas, TX":
            return ResolvedLocation(32.7767, -96.7970, "TX", "Dallas, Texas, USA")
        return ResolvedLocation(39.7392, -104.9903, "CO", "Denver, Colorado, USA")

    def reverse(self, latitude, longitude):
        return ResolvedLocation(latitude, longitude, "TX", "Texas, USA")


class FakeRouter:
    def __init__(self):
        self.calls = 0

    def directions(self, start, finish):
        self.calls += 1
        return Route([list(start), list(finish)], 300 * 1609.344, 18000)


@pytest.fixture
def client():
    cache.clear()
    return APIClient()


@pytest.mark.django_db
@override_settings(NOMINATIM_USER_AGENT="test-suite/1.0 contact test@example.org")
def test_post_plan_persists_response_and_cache_skips_routing(client, monkeypatch):
    from fuel.services import planning

    router = FakeRouter()
    monkeypatch.setattr(planning, "_geocoding_provider", lambda: FakeGeocoder())
    monkeypatch.setattr(planning, "_routing_provider", lambda: router)
    request_data = {"start": "Dallas, TX", "finish": "Denver, CO"}
    first = client.post("/api/v1/fuel-plans/", request_data, format="json")
    assert first.status_code == 201
    assert first.data["meta"]["routing_calls_made"] == 1
    assert router.calls == 1
    assert FuelPlan.objects.count() == 1
    second = client.post("/api/v1/fuel-plans/", request_data, format="json")
    assert second.status_code == 201
    assert second.data["meta"]["routing_calls_made"] == 0
    assert second.data["meta"]["cache_hit"] is True
    assert router.calls == 1
    assert client.get(f"/api/v1/fuel-plans/{first.data['id']}/").data["id"] == first.data["id"]


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "post"])
def test_compact_coordinates_preserve_full_saved_map(client, monkeypatch, method):
    from fuel.services import planning

    coordinates = [[-96.8 + index * 0.01, 32.8 + index * 0.01] for index in range(10)]
    router = FakeRouter()
    monkeypatch.setattr(
        router, "directions", lambda start, finish: Route(coordinates, 300 * 1609.344, 18000)
    )
    monkeypatch.setattr(planning, "_geocoding_provider", lambda: FakeGeocoder())
    monkeypatch.setattr(planning, "_routing_provider", lambda: router)
    payload = {"start": "Dallas, TX", "finish": "Denver, CO"}
    if method == "post":
        response = client.post("/api/v1/fuel-plans/", payload, format="json")
    else:
        response = client.get("/api/v1/fuel-plans/", payload)

    assert response.status_code == 201
    preview = [coordinates[index] for index in (0, 3, 6, 9)]
    assert response.data["route"]["geometry"]["coordinates"] == preview
    plan = FuelPlan.objects.get(id=response.data["id"])
    assert plan.output_json["route"]["geometry"]["coordinates"] == coordinates
    saved = client.get(f"/api/v1/fuel-plans/{plan.id}/")
    assert saved.data["route"]["geometry"]["coordinates"] == preview
    map_response = client.get(response.data["map_url"])
    assert map_response.status_code == 200
    assert map_response.context["route"]["coordinates"] == coordinates


def test_invalid_location_returns_consistent_validation_error(client):
    response = client.post(
        "/api/v1/fuel-plans/", {"start": {"lat": 200, "lon": 5}, "finish": "Denver"}, format="json"
    )
    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"


@pytest.mark.django_db
def test_map_json_escapes_station_names(client):
    plan_id = uuid.uuid4()
    payload = {
        "route": {
            "geometry": {"type": "LineString", "coordinates": [[-96.0, 32.0], [-95.0, 33.0]]}
        },
        "stops": [
            {
                "order": 1,
                "name": "<img src=x onerror=alert(1)>",
                "address": "A",
                "city": "B",
                "state": "TX",
                "lat": 32,
                "lon": -96,
                "price_per_gallon": 3.2,
            }
        ],
    }
    FuelPlan.objects.create(id=plan_id, request_json={}, output_json=payload)
    response = client.get(f"/api/v1/fuel-plans/{plan_id}/map/")
    assert response.status_code == 200
    assert "\\u003Cimg" in response.content.decode()
    assert "<img src=x" not in response.content.decode()
    assert 'number.className = "fuel-stop-number"' in response.content.decode()


@pytest.mark.django_db
def test_get_query_contract(client, monkeypatch):
    from fuel.services import planning

    monkeypatch.setattr(planning, "_geocoding_provider", lambda: FakeGeocoder())
    monkeypatch.setattr(planning, "_routing_provider", lambda: FakeRouter())
    response = client.get("/api/v1/fuel-plans/?start=Dallas%2C%20TX&finish=Denver%2C%20CO")
    assert response.status_code == 201
    assert json.loads(response.content)["route"]["distance_miles"] == 300


@pytest.mark.django_db
def test_coordinate_geocoding_is_cached(client, monkeypatch):
    from fuel.services import planning

    cache.clear()
    geocoder = FakeGeocoder()
    geocoder.reverse = lambda latitude, longitude: ResolvedLocation(
        latitude, longitude, "TX", "Texas, USA"
    )
    router = FakeRouter()
    monkeypatch.setattr(planning, "_geocoding_provider", lambda: geocoder)
    monkeypatch.setattr(planning, "_routing_provider", lambda: router)
    payload = {"start": {"lat": 32.0, "lon": -96.0}, "finish": {"lat": 33.0, "lon": -95.0}}
    first = client.post("/api/v1/fuel-plans/", payload, format="json")
    second = client.post("/api/v1/fuel-plans/", payload, format="json")
    assert first.status_code == second.status_code == 201
    assert second.data["meta"]["cache_hit"] is True
    assert router.calls == 1
    assert callable(geocoder.reverse)


@pytest.mark.django_db
def test_outside_us_and_same_location_fail_before_routing(client, monkeypatch):
    from fuel.services import planning

    class NonUsGeocoder(FakeGeocoder):
        def geocode(self, query):
            return ResolvedLocation(49.0, -123.0, "BC", "Canada")

    router = FakeRouter()
    monkeypatch.setattr(planning, "_geocoding_provider", lambda: NonUsGeocoder())
    monkeypatch.setattr(planning, "_routing_provider", lambda: router)
    response = client.post("/api/v1/fuel-plans/", {"start": "A", "finish": "B"}, format="json")
    assert response.status_code == 400
    assert response.data["error"]["code"] == "outside_usa"
    assert router.calls == 0

    cache.clear()
    monkeypatch.setattr(planning, "_geocoding_provider", lambda: FakeGeocoder())
    response = client.post(
        "/api/v1/fuel-plans/", {"start": "Dallas, TX", "finish": "Dallas, TX"}, format="json"
    )
    assert response.status_code == 400
    assert response.data["error"]["code"] == "same_location"
    assert router.calls == 0


@pytest.mark.django_db
def test_provider_failures_and_unresolved_route_have_consistent_errors(client, monkeypatch):
    from fuel.services import planning

    class BrokenGeocoder:
        def geocode(self, query):
            raise RuntimeError("network unavailable")

        def reverse(self, latitude, longitude):
            return None

    monkeypatch.setattr(planning, "_geocoding_provider", lambda: BrokenGeocoder())
    response = client.post("/api/v1/fuel-plans/", {"start": "A", "finish": "B"}, format="json")
    assert response.status_code == 502
    assert response.data["error"]["code"] == "geocoding_failed"

    class BrokenRouter:
        def directions(self, start, finish):
            raise ProviderError("route unavailable")

    cache.clear()
    monkeypatch.setattr(planning, "_geocoding_provider", lambda: FakeGeocoder())
    monkeypatch.setattr(planning, "_routing_provider", lambda: BrokenRouter())
    response = client.post(
        "/api/v1/fuel-plans/", {"start": "Dallas, TX", "finish": "Denver, CO"}, format="json"
    )
    assert response.status_code == 502
    assert response.data["error"]["code"] == "routing_failed"


@pytest.mark.django_db
def test_unresolved_route_and_impossible_fuel_plan(client, monkeypatch):
    from fuel.services import planning

    class InvalidRouter:
        def directions(self, start, finish):
            return Route([], 0, 0)

    monkeypatch.setattr(planning, "_geocoding_provider", lambda: FakeGeocoder())
    monkeypatch.setattr(planning, "_routing_provider", lambda: InvalidRouter())
    response = client.post(
        "/api/v1/fuel-plans/", {"start": "Dallas, TX", "finish": "Denver, CO"}, format="json"
    )
    assert response.status_code == 502
    assert response.data["error"]["code"] == "routing_failed"

    cache.clear()

    class LongRouter:
        def directions(self, start, finish):
            return Route([list(start), list(finish)], 1100 * 1609.344, 50000)

    monkeypatch.setattr(planning, "_routing_provider", lambda: LongRouter())
    response = client.post(
        "/api/v1/fuel-plans/", {"start": "Dallas, TX", "finish": "Denver, CO"}, format="json"
    )
    assert response.status_code == 422
    assert response.data["error"]["code"] == "no_feasible_fuel_plan"
    assert response.data["error"]["details"]["gap_miles"] == 1100
