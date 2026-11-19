from django.contrib import admin

from fuel.models import FuelPlan, GeocodeCache, Station

admin.site.register([Station, GeocodeCache, FuelPlan])
