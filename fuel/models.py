from django.db import models


class Station(models.Model):
    opis_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.CharField(max_length=32, blank=True)
    price_per_gallon = models.DecimalField(max_digits=7, decimal_places=3)
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)
    geocode_quality = models.CharField(max_length=12, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["latitude", "longitude"], name="station_lat_lon_idx")]
        ordering = ["opis_id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.opis_id})"


class GeocodeCache(models.Model):
    query = models.CharField(max_length=500, unique=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    state = models.CharField(max_length=2, blank=True)
    quality = models.CharField(max_length=12, default="failed")
    created_at = models.DateTimeField(auto_now=True)


class FuelPlan(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    request_json = models.JSONField()
    output_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
