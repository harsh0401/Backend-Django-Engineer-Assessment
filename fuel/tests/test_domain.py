import itertools
import random

import pytest

from fuel.domain.algorithm import FuelStation, NoFeasibleRoute, optimize_fuel_stops
from fuel.domain.geometry import cumulative_route_miles, haversine_miles, project_stations_to_route


def station(identifier, mile, price, *, lat=32.0, lon=-96.0):
    return FuelStation(identifier, identifier, "address", "City", "TX", lat, lon, price, mile)


def brute_force(route_miles, stations, range_miles=20, mpg=10, tick=0.5):
    capacity = range_miles / mpg
    best = 0.0 if route_miles <= capacity * mpg else float("inf")
    for count in range(1, len(stations) + 1):
        for subset in itertools.combinations(stations, count):
            states = {(0, 0.0)}
            for candidate in subset:
                next_states = set()
                for ticks, cost in states:
                    fuel = capacity + ticks * tick - candidate.mile_marker / mpg
                    if fuel < -1e-9:
                        continue
                    max_ticks = int((capacity - capacity + candidate.mile_marker / mpg) // tick)
                    for bought in range(ticks, max_ticks + 1):
                        next_states.add(
                            (bought, cost + (bought - ticks) * tick * candidate.price_per_gallon)
                        )
                states = next_states
            for ticks, cost in states:
                if capacity + ticks * tick >= route_miles / mpg - 1e-9:
                    best = min(best, cost)
    return round(best, 2)


def test_short_trip_needs_no_stop():
    result = optimize_fuel_stops(400, [], range_miles=500)
    assert result.stops == ()
    assert result.total_cost_usd == 0


def test_long_trip_uses_multiple_stops_and_optimal_prices():
    result = optimize_fuel_stops(
        1150, [station("A", 400, 4), station("B", 700, 2), station("C", 900, 3)]
    )
    assert [stop.station.identifier for stop in result.stops] == ["A", "B"]
    assert result.total_gallons == 65.0
    assert result.total_cost_usd == 170.0


def test_no_station_gap_has_leg_details():
    with pytest.raises(NoFeasibleRoute) as error:
        optimize_fuel_stops(1100, [station("A", 200, 3)], range_miles=500)
    assert error.value.details["gap_miles"] == 900


def test_equal_prices_are_deterministic():
    result = optimize_fuel_stops(800, [station("B", 400, 3), station("A", 400, 3)])
    assert result.stops[0].station.identifier == "A"


def test_colocated_stations_choose_lower_price():
    result = optimize_fuel_stops(800, [station("expensive", 400, 4), station("cheap", 400, 2)])
    assert len(result.stops) == 1
    assert result.stops[0].station.identifier == "cheap"


def test_start_empty_requires_a_station_at_origin():
    with pytest.raises(NoFeasibleRoute):
        optimize_fuel_stops(100, [], start_full_tank=False)
    result = optimize_fuel_stops(100, [station("origin", 0, 2)], start_full_tank=False)
    assert result.total_gallons == 10
    assert result.total_cost_usd == 20


@pytest.mark.parametrize("seed", range(12))
def test_dynamic_program_matches_exhaustive_stop_subsets(seed):
    random.seed(seed)
    route_miles = random.choice([24, 28, 32, 36])
    stations = [
        station(str(i), mile, random.choice([2.0, 3.0, 4.0]))
        for i, mile in enumerate([8, 14, 20, 26])
        if mile < route_miles
    ]
    expected = brute_force(route_miles, stations)
    try:
        actual = optimize_fuel_stops(route_miles, stations, range_miles=20).total_cost_usd
    except NoFeasibleRoute:
        actual = float("inf")
    assert actual == expected


def test_route_projection_assigns_closest_segment_mile_marker():
    projected = project_stations_to_route(
        [(-97.0, 32.0), (-96.0, 32.0)],
        [{"longitude": -96.5, "latitude": 32.01, "name": "station"}],
        corridor_width_miles=5,
    )
    assert len(projected) == 1
    assert projected[0]["mile_marker"] == pytest.approx(
        cumulative_route_miles([(-97, 32), (-96, 32)])[-1] / 2, rel=0.01
    )


def test_haversine_known_city_pair_is_reasonable():
    distance = haversine_miles(-96.7970, 32.7767, -104.9903, 39.7392)
    assert distance == pytest.approx(663, abs=8)
