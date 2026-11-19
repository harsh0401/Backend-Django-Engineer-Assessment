import math

from django.db.models import QuerySet

from fuel.models import Station


def stations_in_route_bounds(
    route_points: list[list[float]], corridor_width_miles: float
) -> QuerySet[Station]:
    latitudes = [point[1] for point in route_points]
    longitudes = [point[0] for point in route_points]
    latitude_padding = corridor_width_miles / 69.0
    max_abs_latitude = min(89.0, max(abs(value) for value in latitudes) + latitude_padding)
    longitude_padding = corridor_width_miles / max(
        1.0, 69.172 * abs(math.cos(math.radians(max_abs_latitude)))
    )
    return Station.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
        latitude__gte=min(latitudes) - latitude_padding,
        latitude__lte=max(latitudes) + latitude_padding,
        longitude__gte=max(-180.0, min(longitudes) - longitude_padding),
        longitude__lte=min(180.0, max(longitudes) + longitude_padding),
    )
