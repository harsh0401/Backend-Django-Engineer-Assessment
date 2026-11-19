import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from fuel.models import Station
from geo.providers import US_STATES

NON_US = {"AB", "BC", "MB", "NB", "NS", "ON", "QC", "SK", "YT"}


def normalize_rows(rows):
    stations = {}
    dropped_non_us = 0
    dropped_price = 0
    collapsed_rows = 0
    for row in rows:
        state = row["State"].strip().upper()
        if state in NON_US or state not in US_STATES:
            dropped_non_us += 1
            continue
        try:
            price = Decimal(row["Retail Price"].strip())
            if not price.is_finite() or price <= 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            dropped_price += 1
            continue
        identifier = row["OPIS Truckstop ID"].strip()
        if not identifier:
            continue
        station = {
            "opis_id": identifier,
            "name": row["Truckstop Name"].strip(),
            "address": row["Address"].strip(),
            "city": row["City"].strip(),
            "state": state,
            "rack_id": row["Rack ID"].strip(),
            "price_per_gallon": price,
        }
        previous = stations.get(identifier)
        if previous is not None:
            collapsed_rows += 1
        if previous is None or price < previous["price_per_gallon"]:
            stations[identifier] = station
    return list(stations.values()), dropped_non_us, dropped_price, collapsed_rows


class Command(BaseCommand):
    help = "Load and normalize the fuel price CSV into the station database"

    def add_arguments(self, parser):
        default_path = settings.BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"
        root_path = settings.BASE_DIR / "fuel-prices-for-be-assessment.csv"
        if not default_path.is_file() and root_path.is_file():
            default_path = root_path
        parser.add_argument("--file", default=str(default_path))

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"Fuel price CSV not found: {path}")
        with path.open(encoding="utf-8-sig", newline="") as source:
            rows, dropped_non_us, dropped_price, collapsed_rows = normalize_rows(
                csv.DictReader(source)
            )
        existing_ids = set(
            Station.objects.filter(opis_id__in=[row["opis_id"] for row in rows]).values_list(
                "opis_id", flat=True
            )
        )
        objects = [Station(**row) for row in rows]
        Station.objects.bulk_create(
            objects,
            batch_size=500,
            update_conflicts=True,
            unique_fields=["opis_id"],
            update_fields=["name", "address", "city", "state", "rack_id", "price_per_gallon"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(rows)} unique stations; updated {len(existing_ids)} existing; "
                f"dropped {dropped_non_us} non-US/invalid-state rows and "
                f"{dropped_price} invalid-price rows; "
                f"collapsed {collapsed_rows} duplicate rows"
            )
        )
