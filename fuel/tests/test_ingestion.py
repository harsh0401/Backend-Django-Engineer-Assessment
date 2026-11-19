from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from fuel.management.commands.load_stations import normalize_rows
from fuel.models import GeocodeCache, Station
from geo.providers import GeocodingProviderError, ResolvedLocation


def row(identifier, state="TX", price="3.50", name="Pilot", address="I-35 Exit 2"):
    return {
        "OPIS Truckstop ID": identifier,
        "Truckstop Name": name,
        "Address": address,
        "City": "Dallas",
        "State": state,
        "Rack ID": "R1",
        "Retail Price": price,
    }


def test_normalization_filters_non_us_and_invalid_prices_and_keeps_lowest():
    rows = [
        row("123", price="4.20", name="PILOT #1243"),
        row("123", price="3.80", name="PILOT TRAVEL CENTER #1243"),
        row("foreign", state="ON"),
        row("nan", price="NaN"),
        row("zero", price="0"),
    ]
    stations, dropped_non_us, dropped_price, collapsed_rows = normalize_rows(rows)
    assert len(stations) == 1
    assert stations[0]["name"] == "PILOT TRAVEL CENTER #1243"
    assert stations[0]["price_per_gallon"] == Decimal("3.80")
    assert (dropped_non_us, dropped_price, collapsed_rows) == (1, 2, 1)


@pytest.mark.django_db
def test_load_command_is_idempotent_and_logs_duplicate_collapses(tmp_path, capsys):
    import csv

    path = tmp_path / "fuel.csv"
    rows = [
        row("123", price="4.20"),
        row("123", price="3.80"),
        row("456", price="3.10", state="CA"),
    ]
    with path.open("w", newline="", encoding="utf-8") as source:
        writer = csv.DictWriter(source, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    call_command("load_stations", file=str(path))
    call_command("load_stations", file=str(path))
    assert Station.objects.count() == 2
    assert Station.objects.get(opis_id="123").price_per_gallon == Decimal("3.800")
    assert capsys.readouterr().out.count("collapsed 1 duplicate rows") == 2


@pytest.mark.django_db
def test_geocode_command_falls_back_to_city_and_is_resumable(monkeypatch):
    from fuel.management.commands import geocode_stations

    station = Station.objects.create(
        opis_id="1",
        name="Truckstop",
        address="I-35 Exit 2",
        city="Dallas",
        state="TX",
        price_per_gallon="3.500",
    )

    class FakeProvider:
        calls = []

        def __init__(self, user_agent):
            pass

        def geocode(self, query):
            self.calls.append(query)
            if query.startswith("I-35"):
                return None
            return ResolvedLocation(32.7767, -96.7970, "TX", "Dallas, TX")

    monkeypatch.setattr(
        geocode_stations,
        "get_geocoding_provider",
        lambda *args: FakeProvider("test"),
    )
    call_command("geocode_stations", limit=1)
    station.refresh_from_db()
    assert station.geocode_quality == "city"
    assert station.latitude == pytest.approx(32.7767)
    assert GeocodeCache.objects.count() == 2
    assert len(FakeProvider.calls) == 2
    call_command("geocode_stations", limit=1)
    assert len(FakeProvider.calls) == 2


@pytest.mark.django_db
def test_geocode_command_retries_transient_provider_errors(monkeypatch):
    from fuel.management.commands import geocode_stations

    station = Station.objects.create(
        opis_id="2",
        name="Truckstop",
        address="100 Main St",
        city="Austin",
        state="TX",
        price_per_gallon="3.500",
    )

    class FlakyProvider:
        unavailable = True
        calls = 0

        def __init__(self, user_agent):
            pass

        def geocode(self, query):
            self.calls += 1
            if self.unavailable:
                raise RuntimeError("temporary network failure")
            return ResolvedLocation(30.2672, -97.7431, "TX", "Austin, TX")

    provider = FlakyProvider("test")
    monkeypatch.setattr(geocode_stations, "get_geocoding_provider", lambda *args: provider)
    monkeypatch.setattr(geocode_stations.time, "sleep", lambda seconds: None)
    call_command("geocode_stations", limit=1)
    assert set(GeocodeCache.objects.values_list("quality", flat=True)) == {"error"}

    provider.unavailable = False
    call_command("geocode_stations", limit=1)
    station.refresh_from_db()
    assert station.geocode_quality == "address"
    assert station.latitude == pytest.approx(30.2672)
    assert provider.calls == 3


@pytest.mark.django_db
def test_geocode_command_stops_immediately_on_forbidden(monkeypatch):
    from fuel.management.commands import geocode_stations

    Station.objects.create(
        opis_id="3",
        name="Truckstop",
        address="100 Main St",
        city="Austin",
        state="TX",
        price_per_gallon="3.500",
    )

    class ForbiddenProvider:
        calls = 0

        def geocode(self, query):
            self.calls += 1
            raise GeocodingProviderError("forbidden", status_code=403)

    provider = ForbiddenProvider()
    monkeypatch.setattr(geocode_stations, "get_geocoding_provider", lambda *args: provider)
    with pytest.raises(CommandError, match="HTTP 403"):
        call_command("geocode_stations")
    assert provider.calls == 1
