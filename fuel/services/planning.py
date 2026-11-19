from __future__ import annotations

import hashlib
import json
import time
import uuid

from django.conf import settings
from django.core.cache import cache

from fuel.domain.algorithm import FuelStation, NoFeasibleRoute, optimize_fuel_stops
from fuel.domain.geometry import project_stations_to_route
from fuel.models import FuelPlan
from fuel.repositories import stations_in_route_bounds
from geo.providers import US_STATES, GeocodingProvider, ResolvedLocation, get_geocoding_provider
from routing.providers import OpenRouteServiceProvider, OsrmProvider, ProviderError, RoutingProvider


class PlanningError(Exception):
    def __init__(self, code: str, message: str, status: int, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}


def _routing_provider() -> RoutingProvider:
    if settings.ROUTING_PROVIDER == "osrm":
        return OsrmProvider()
    return OpenRouteServiceProvider(settings.ORS_API_KEY)


def _geocoding_provider() -> GeocodingProvider:
    return get_geocoding_provider(
        settings.GEOCODING_PROVIDER,
        settings.ORS_API_KEY,
        settings.NOMINATIM_USER_AGENT,
    )


def _cache_key(prefix: str, value: object) -> str:
    packed = json.dumps(value, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(packed.encode()).hexdigest()
    return f"fuel:{prefix}:{digest}"


def _resolve(value: str | dict, provider: GeocodingProvider) -> tuple[ResolvedLocation, bool]:
    if isinstance(value, dict):
        latitude, longitude = float(value["lat"]), float(value["lon"])
        key = _cache_key("reverse", [round(latitude, 5), round(longitude, 5)])
        cached = cache.get(key)
        if cached is not None:
            location = ResolvedLocation(**cached)
            if location.state not in US_STATES:
                raise PlanningError(
                    "outside_usa", "Both locations must be within the 50 US states or DC", 400
                )
            return location, True
        location = provider.reverse(latitude, longitude)
    else:
        key = _cache_key("geocode", value.strip().lower())
        cached = cache.get(key)
        if cached is not None:
            location = ResolvedLocation(**cached)
            return location, True
        location = provider.geocode(value)
    if location is None or location.state not in US_STATES:
        raise PlanningError(
            "outside_usa", "Both locations must resolve inside the 50 US states or DC", 400
        )
    cache.set(key, location.__dict__, settings.CACHE_TTL_SECONDS)
    return location, False


def build_fuel_plan(
    start_value: str | dict,
    finish_value: str | dict,
    *,
    routing_provider: RoutingProvider | None = None,
    geocoding_provider: GeocodingProvider | None = None,
) -> tuple[dict, str]:
    started = time.perf_counter()
    try:
        geocoder = geocoding_provider or _geocoding_provider()
        start, start_cached = _resolve(start_value, geocoder)
        finish, finish_cached = _resolve(finish_value, geocoder)
    except (RuntimeError, ValueError) as error:
        raise PlanningError("geocoding_failed", str(error), 502) from error
    if (
        abs(start.latitude - finish.latitude) < 1e-8
        and abs(start.longitude - finish.longitude) < 1e-8
    ):
        raise PlanningError("same_location", "Start and finish must be different locations", 400)

    coordinates_key = [
        round(start.longitude, 5),
        round(start.latitude, 5),
        round(finish.longitude, 5),
        round(finish.latitude, 5),
    ]
    route_key = _cache_key("route", coordinates_key)
    route_data = cache.get(route_key)
    cache_hit = route_data is not None
    routing_calls = 0
    if route_data is None:
        provider = routing_provider or _routing_provider()
        try:
            route = provider.directions(
                (start.longitude, start.latitude), (finish.longitude, finish.latitude)
            )
        except ProviderError as error:
            raise PlanningError("routing_failed", str(error), 502) from error
        except Exception as error:
            raise PlanningError(
                "routing_failed", f"Route could not be resolved: {error}", 502
            ) from error
        routing_calls = 1
        route_data = {
            "coordinates": route.coordinates,
            "distance_meters": route.distance_meters,
            "duration_seconds": route.duration_seconds,
        }
        if not route_data["coordinates"] or route_data["distance_meters"] <= 0:
            raise PlanningError(
                "routing_failed", "Routing provider returned an empty or zero-length route", 502
            )
        cache.set(route_key, route_data, settings.CACHE_TTL_SECONDS)

    route_points = route_data["coordinates"]
    route_miles = float(route_data["distance_meters"]) / 1609.344
    if route_miles <= 0:
        raise PlanningError(
            "routing_failed", "Routing provider returned an invalid route distance", 502
        )
    station_rows = list(
        stations_in_route_bounds(route_points, settings.CORRIDOR_WIDTH_MILES).values(
            "opis_id",
            "name",
            "address",
            "city",
            "state",
            "latitude",
            "longitude",
            "price_per_gallon",
            "geocode_quality",
        )
    )
    projected = project_stations_to_route(route_points, station_rows, settings.CORRIDOR_WIDTH_MILES)
    candidates = [
        FuelStation(
            identifier=row["opis_id"],
            name=row["name"],
            address=row["address"],
            city=row["city"],
            state=row["state"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            price_per_gallon=float(row["price_per_gallon"]),
            mile_marker=row["mile_marker"],
            geocode_quality=row["geocode_quality"],
        )
        for row in projected
    ]
    try:
        result = optimize_fuel_stops(
            route_miles,
            candidates,
            range_miles=settings.RANGE_MILES,
            mpg=settings.MPG,
            start_full_tank=settings.START_FULL_TANK,
            tick_gallons=settings.FUEL_TICK_GALLONS,
        )
    except NoFeasibleRoute as error:
        raise PlanningError("no_feasible_fuel_plan", str(error), 422, error.details) from error

    duration_minutes = float(route_data["duration_seconds"]) / 60
    plan_id = str(uuid.uuid4())
    output = {
        "id": plan_id,
        "request": {
            "start": start_value,
            "finish": finish_value,
            "resolved_start": {
                "lat": start.latitude,
                "lon": start.longitude,
                "state": start.state,
                "label": start.label,
            },
            "resolved_finish": {
                "lat": finish.latitude,
                "lon": finish.longitude,
                "state": finish.state,
                "label": finish.label,
            },
        },
        "route": {
            "distance_miles": round(route_miles, 2),
            "duration_minutes": round(duration_minutes, 1),
            "geometry": {"type": "LineString", "coordinates": route_points},
        },
        "stops": [
            {
                "order": index,
                "name": stop.station.name,
                "address": stop.station.address,
                "city": stop.station.city,
                "state": stop.station.state,
                "lat": stop.station.latitude,
                "lon": stop.station.longitude,
                "price_per_gallon": round(stop.station.price_per_gallon, 3),
                "mile_marker": round(stop.station.mile_marker, 2),
                "gallons_purchased": round(stop.gallons_purchased, 2),
                "cost_usd": round(stop.cost_usd, 2),
                "geocode_quality": stop.station.geocode_quality,
            }
            for index, stop in enumerate(result.stops, start=1)
        ],
        "summary": {
            "total_gallons": result.total_gallons,
            "total_cost_usd": result.total_cost_usd,
            "number_of_stops": len(result.stops),
            "assumptions": [
                "Vehicle starts with a full tank"
                if settings.START_FULL_TANK
                else "Vehicle starts with an empty tank",
                f"Fuel economy is {settings.MPG:g} miles per gallon",
                f"Maximum range is {settings.RANGE_MILES:g} miles",
            ],
        },
        "map_url": f"/api/v1/fuel-plans/{plan_id}/map/",
        "meta": {
            "cache_hit": cache_hit and start_cached and finish_cached,
            "routing_calls_made": routing_calls,
            "compute_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }
    FuelPlan.objects.create(
        id=uuid.UUID(plan_id),
        request_json={"start": start_value, "finish": finish_value},
        output_json=output,
    )
    return output, plan_id
