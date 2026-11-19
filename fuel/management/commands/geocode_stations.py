import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from fuel.models import GeocodeCache, Station
from geo.providers import GeocodingProviderError, get_geocoding_provider


class Command(BaseCommand):
    help = "Geocode stations offline with the configured provider and resumable DB cache"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        try:
            provider = get_geocoding_provider(
                settings.GEOCODING_PROVIDER,
                settings.ORS_API_KEY,
                settings.NOMINATIM_USER_AGENT,
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        queryset = Station.objects.filter(latitude__isnull=True).order_by("opis_id")
        if options["limit"]:
            queryset = queryset[: options["limit"]]
        last_request = 0.0
        updated = 0
        for station in queryset.iterator():
            address_query = f"{station.address}, {station.city}, {station.state}, USA"
            city_query = f"{station.city}, {station.state}, USA"
            result = None
            quality = "failed"
            for query, source_quality in ((address_query, "address"), (city_query, "city")):
                cached = GeocodeCache.objects.filter(query=query).first()
                if cached and cached.quality != "error":
                    result = cached if cached.latitude is not None else None
                else:
                    wait = 1.0 - (time.monotonic() - last_request)
                    if wait > 0:
                        time.sleep(wait)
                    last_request = time.monotonic()
                    request_failed = False
                    try:
                        result = provider.geocode(query)
                    except GeocodingProviderError as error:
                        if error.status_code in {401, 403, 429}:
                            raise CommandError(
                                f"Geocoding provider returned HTTP {error.status_code}: {error}; "
                                "stopping the batch. Check the API key, provider permissions, "
                                "quota, or rate limits, then rerun the command."
                            ) from error
                        message = f"Geocoding failed for {query}: {error}"
                        self.stderr.write(self.style.WARNING(message))
                        result = None
                    except RuntimeError as error:
                        message = f"Geocoding failed for {query}: {error}"
                        self.stderr.write(self.style.WARNING(message))
                        result = None
                        request_failed = True
                    if result:
                        cache_quality = source_quality
                    elif request_failed:
                        cache_quality = "error"
                    else:
                        cache_quality = "failed"
                    GeocodeCache.objects.update_or_create(
                        query=query,
                        defaults={
                            "latitude": result.latitude if result else None,
                            "longitude": result.longitude if result else None,
                            "state": result.state if result else "",
                            "quality": cache_quality,
                        },
                    )
                if result and result.latitude is not None:
                    quality = source_quality
                    break
            if result:
                station.latitude = result.latitude
                station.longitude = result.longitude
            station.geocode_quality = quality
            station.save(update_fields=["latitude", "longitude", "geocode_quality", "updated_at"])
            updated += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {updated} stations; cached address and city results in the database"
            )
        )
