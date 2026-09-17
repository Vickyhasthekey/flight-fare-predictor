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

# Serves public/ at http://127.0.0.1:8000. Find flights needs SERPAPI_API_KEY in the environment.
# Example: SERPAPI_API_KEY=... make api
api:
	uvicorn api.predict:app --reload

full-data:
	fare-signal ingest --input "$(RAW_DATA)" --output data/flight_prices_clean.parquet
	fare-signal build-table --input data/flight_prices_clean.parquet --output data/training_table.parquet
	fare-signal train
	fare-signal backtest --input data/flight_prices_clean.parquet
