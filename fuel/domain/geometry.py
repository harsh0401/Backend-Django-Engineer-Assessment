from __future__ import annotations

import numpy as np

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    longitude_1, latitude_1, longitude_2, latitude_2 = np.radians([lon1, lat1, lon2, lat2])
    delta_longitude = longitude_2 - longitude_1
    delta_latitude = latitude_2 - latitude_1
    value = (
        np.sin(delta_latitude / 2) ** 2
        + np.cos(latitude_1) * np.cos(latitude_2) * np.sin(delta_longitude / 2) ** 2
    )
    return float(2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(value)))


def cumulative_route_miles(points: list[tuple[float, float]]) -> np.ndarray:
    if len(points) < 2:
        raise ValueError("A route needs at least two coordinates")
    coordinates = np.asarray(points, dtype=float)
    lon = np.radians(coordinates[:, 0])
    lat = np.radians(coordinates[:, 1])
    delta_lon = np.diff(lon)
    delta_lat = np.diff(lat)
    value = (
        np.sin(delta_lat / 2) ** 2 + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(delta_lon / 2) ** 2
    )
    segment_miles = 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(value))
    return np.concatenate(([0.0], np.cumsum(segment_miles)))


def project_stations_to_route(
    route_points: list[tuple[float, float]],
    stations: list[dict[str, object]],
    corridor_width_miles: float,
) -> list[dict[str, object]]:
    """Return stations within the corridor with closest-segment route mile markers."""
    if not stations:
        return []
    route = np.asarray(route_points, dtype=float)
    center_lat = np.radians(float(route[:, 1].mean()))
    miles_per_degree_lat = 69.0
    miles_per_degree_lon = 69.172 * np.cos(center_lat)
    route_xy = np.column_stack(
        (route[:, 0] * miles_per_degree_lon, route[:, 1] * miles_per_degree_lat)
    )
    segment_start = route_xy[:-1]
    segment_vector = route_xy[1:] - segment_start
    segment_squared = np.einsum("ij,ij->i", segment_vector, segment_vector)
    cumulative = cumulative_route_miles(route_points)
    segment_lengths = np.diff(cumulative)
    result = []
    for offset in range(0, len(stations), 128):
        chunk = stations[offset : offset + 128]
        station_coordinates = np.asarray(
            [(station["longitude"], station["latitude"]) for station in chunk], dtype=float
        )
        station_xy = np.column_stack(
            (
                station_coordinates[:, 0] * miles_per_degree_lon,
                station_coordinates[:, 1] * miles_per_degree_lat,
            )
        )
        relative = station_xy[:, None, :] - segment_start[None, :, :]
        fractions = np.einsum("sri,ri->sr", relative, segment_vector) / np.maximum(
            segment_squared, 1e-12
        )
        fractions = np.clip(fractions, 0.0, 1.0)
        projected = segment_start[None, :, :] + fractions[:, :, None] * segment_vector[None, :, :]
        distances = np.linalg.norm(station_xy[:, None, :] - projected, axis=2)
        nearest_segments = distances.argmin(axis=1)
        rows = np.arange(len(chunk))
        nearest_distances = distances[rows, nearest_segments]
        mile_markers = (
            cumulative[nearest_segments]
            + fractions[rows, nearest_segments] * segment_lengths[nearest_segments]
        )
        for index, station in enumerate(chunk):
            if nearest_distances[index] <= corridor_width_miles:
                result.append(
                    {
                        **station,
                        "mile_marker": float(mile_markers[index]),
                        "corridor_distance_miles": float(nearest_distances[index]),
                    }
                )
    return result
