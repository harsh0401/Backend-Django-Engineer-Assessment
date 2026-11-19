.PHONY: install migrate load geocode run test lint

install:
	python -m pip install -r requirements-dev.txt

migrate:
	python manage.py migrate

load:
	python manage.py load_stations

geocode:
	python manage.py geocode_stations

run:
	python manage.py runserver

test:
	pytest --cov

lint:
	ruff check .