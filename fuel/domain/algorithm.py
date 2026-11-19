from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FuelStation:
    identifier: str
    name: str
    address: str
    city: str
    state: str
    latitude: float
    longitude: float
    price_per_gallon: float
    mile_marker: float
    geocode_quality: str = "address"


@dataclass(frozen=True)
class FuelStop:
    station: FuelStation
    gallons_purchased: float
    cost_usd: float


@dataclass(frozen=True)
class FuelPlanResult:
    stops: tuple[FuelStop, ...]
    total_gallons: float
    total_cost_usd: float


class NoFeasibleRoute(ValueError):
    def __init__(self, details: dict[str, float | int]):
        super().__init__("No fuel purchase plan can reach the destination")
        self.details = details


def _ceil_ticks(gallons: float, tick_gallons: float) -> int:
    return math.ceil(gallons / tick_gallons - 1e-10)


def _gap_details(
    route_miles: float,
    stations: list[FuelStation],
    max_leg_miles: float,
    initial_fuel_gallons: float,
    mpg: float,
) -> dict[str, float | int]:
    positions = [0.0, *(station.mile_marker for station in stations), route_miles]
    positions.sort()
    for gap_start, gap_end in zip(positions, positions[1:], strict=False):
        gap = gap_end - gap_start
        if gap > max_leg_miles + 1e-8:
            return {
                "gap_start_mile": round(gap_start, 3),
                "gap_end_mile": round(gap_end, 3),
                "gap_miles": round(gap, 3),
                "max_leg_miles": round(max_leg_miles, 3),
            }
    first_station = min((s.mile_marker for s in stations), default=route_miles)
    initial_range = initial_fuel_gallons * mpg
    if first_station > initial_range + 1e-8:
        return {
            "gap_start_mile": 0.0,
            "gap_end_mile": round(first_station, 3),
            "gap_miles": round(first_station, 3),
            "max_leg_miles": round(initial_range, 3),
        }
    return {
        "gap_start_mile": 0.0,
        "gap_end_mile": round(route_miles, 3),
        "gap_miles": round(route_miles, 3),
        "max_leg_miles": round(max_leg_miles, 3),
    }


def optimize_fuel_stops(
    route_miles: float,
    stations: list[FuelStation],
    *,
    range_miles: float = 500.0,
    mpg: float = 10.0,
    start_full_tank: bool = True,
    tick_gallons: float = 0.5,
) -> FuelPlanResult:
    """Minimize purchase cost for discrete fuel purchases and continuous driving use.

    States hold cumulative purchased ticks at each station. Fuel remaining is derived
    from the exact route mileage, avoiding per-leg fuel rounding.
    """
    if route_miles < 0 or range_miles <= 0 or mpg <= 0 or tick_gallons <= 0:
        raise ValueError("Route distance, range, mpg, and purchase increment must be valid")
    capacity = range_miles / mpg
    initial_fuel = capacity if start_full_tank else 0.0
    if route_miles == 0:
        return FuelPlanResult((), 0.0, 0.0)
    candidates = sorted(
        (
            station
            for station in stations
            if 0 <= station.mile_marker < route_miles and station.price_per_gallon > 0
        ),
        key=lambda item: (item.mile_marker, item.price_per_gallon, item.identifier),
    )

    # Each entry maps cumulative half-gallon purchase ticks to its least-cost history.
    histories: list[dict[int, tuple[float, tuple[FuelStop, ...]]]] = []
    positions: list[float] = []
    for index, station in enumerate(candidates):
        mile = station.mile_marker
        max_ticks = math.floor((capacity - initial_fuel + mile / mpg) / tick_gallons + 1e-10)
        current: dict[int, tuple[float, tuple[FuelStop, ...]]] = {}
        minimum_arrival_ticks = max(0, _ceil_ticks(mile / mpg - initial_fuel, tick_gallons))
        predecessor_states = [{0: (0.0, ())}, *histories[:index]]
        price_per_tick = tick_gallons * station.price_per_gallon

        for states in predecessor_states:
            adjusted_best: tuple[float, int, tuple[FuelStop, ...]] | None = None
            for purchased_ticks in range(minimum_arrival_ticks, max_ticks + 1):
                previous_state = states.get(purchased_ticks)
                if previous_state is not None:
                    previous_cost, previous_stops = previous_state
                    adjusted = (
                        previous_cost - purchased_ticks * price_per_tick,
                        purchased_ticks,
                        previous_stops,
                    )
                    if adjusted_best is None or adjusted[0] < adjusted_best[0] - 1e-9:
                        adjusted_best = adjusted
                if adjusted_best is None:
                    continue
                previous_ticks = adjusted_best[1]
                previous_stops = adjusted_best[2]
                gallons = (purchased_ticks - previous_ticks) * tick_gallons
                added_cost = gallons * station.price_per_gallon
                new_stops = previous_stops
                if gallons:
                    new_stops = (*previous_stops, FuelStop(station, gallons, added_cost))
                total_cost = adjusted_best[0] + purchased_ticks * price_per_tick
                old = current.get(purchased_ticks)
                if old is None or total_cost < old[0] - 1e-9:
                    current[purchased_ticks] = (total_cost, new_stops)
        histories.append(current)
        positions.append(station.mile_marker)

    best: tuple[float, tuple[FuelStop, ...]] | None = None
    if initial_fuel >= route_miles / mpg:
        best = (0.0, ())
    all_states = [{0: (0.0, ())}, *(states for _, states in zip(positions, histories, strict=True))]
    for states in all_states:
        for ticks, (cost, stops) in states.items():
            if initial_fuel + ticks * tick_gallons >= route_miles / mpg - 1e-9:
                if best is None or cost < best[0] - 1e-9:
                    best = (cost, stops)

    if best is None:
        raise NoFeasibleRoute(_gap_details(route_miles, candidates, range_miles, initial_fuel, mpg))
    total_cost, chosen_stops = best
    total_gallons = sum(stop.gallons_purchased for stop in chosen_stops)
    return FuelPlanResult(chosen_stops, round(total_gallons, 3), round(total_cost, 2))
