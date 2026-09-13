PYTHON ?= python3
RAW_DATA ?= /Users/yuvia/Downloads/itineraries\ 2.csv

.PHONY: install test lint backtest api full-data

install:
	$(PYTHON) -m pip install -e ".[dev,analysis]"

test:
	pytest -q

lint:
	ruff check .

backtest:
	fare-signal backtest --input data/sample_flight_trajectories.csv

api:
	uvicorn api.predict:app --reload

full-data:
	fare-signal ingest --input "$(RAW_DATA)" --output data/flight_prices_clean.parquet
	fare-signal build-table --input data/flight_prices_clean.parquet --output data/training_table.parquet
	fare-signal train
	fare-signal backtest --input data/flight_prices_clean.parquet
