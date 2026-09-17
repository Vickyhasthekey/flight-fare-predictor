# FareSignal

FareSignal is an end-to-end flight-fare prediction and booking-decision platform. It learns the
remaining price curve for a route and departure date, anchors that curve to the fare a traveler sees
today, and returns a practical **BUY NOW** or **WAIT** recommendation with an estimated purchase
window.

The project goes beyond reporting regression accuracy: it includes an out-of-core data pipeline for
the 82-million-row Expedia dataset, time-based model evaluation, a historical booking simulator,
an API, a browser interface, automated tests, and reproducible CLI workflows.

## What is implemented

- DuckDB ingestion of the approximately 31 GB / 82M-row source CSV without loading it into pandas
- Validation, filtering, route-level distance imputation, and compressed Parquet output
- Daily market curves based on the cheapest observed route/date/stop-type fare
- Remaining-curve gradient boosting using route, lead time, current fare, calendar, distance, stop
  type, weekend, and holiday features
- Chronological train/validation/test splits
- BUY/WAIT recommendations pinned to a chosen itinerary fare (or a published current fare)
- Live one-way itinerary search (SerpAPI Google Flights) so travelers pick a specific flight before the curve
- Validation-only decision-threshold selection
- Held-out booking backtest against buy-now, always-wait, trailing-median, random, and oracle policies
- FastAPI and legacy Vercel-compatible WSGI endpoints
- Responsive browser UI with predicted fare curve and purchase window
- Docker packaging, GitHub Actions CI, and reproducible Make targets
- 51 automated tests plus Ruff configuration and installable packaging

## Architecture

```text
82M-row itineraries.csv
        |
DuckDB validation + cleaning
        |
compressed Parquet market data
        |
daily route/date/stop curves
        |
remaining-fare training pairs
        |
time split -> model selection -> saved model
        |
historical backtest + policy comparison
        |
FastAPI -> browser UI / API clients
```

## Modeling task

For a traveler viewing a fare `d` days before departure, the model estimates the relative fare at
each remaining lead day:

```text
relative future fare = future best fare / current best fare
```

Predicting a relative curve lets the service preserve the learned temporal shape while scaling it to
the price visible to the user. A recommendation is `WAIT` only when the estimated improvement clears
a threshold selected using validation-period booking outcomes.

All splits use historical search dates. The model is trained on earlier observations and evaluated on
later observations; rows are never randomly shuffled across time.

## Backtest design

The simulator recreates decisions at approximately 21, 14, and 7 days before departure. For each
historical decision:

1. The model sees the current fare and information available at that date.
2. It predicts the remaining fare curve and selects a purchase day.
3. The simulator charges the **actual observed fare** on that day, not the predicted fare.
4. Savings are measured against buying immediately.
5. The decision threshold is tuned on a validation period and applied once to the final test period.

See [RESULTS.md](RESULTS.md) for the verified sample evaluation. The current result is intentionally
reported even though it exposes a weakness in the inherited model; the backtest is designed to catch
that weakness rather than hide it.

## Repository structure

```text
api/                 FastAPI + Vercel-compatible prediction endpoint
artifacts/           generated model and booking evaluation reports
configs/             full workflow configuration
data/                public development samples; full data remains ignored
models/              trained model bundle
notebooks/           generated analytical figures
public/              browser application
src/
  backtest.py        historical booking simulator and policy evaluation
  cli.py             unified command-line interface
  data_pipeline.py   raw CSV validation and out-of-core Parquet pipeline
  train_model.py     temporal training and model selection
  recommend.py       production recommendation logic
tests/               feature, model, API, scraper, and backtest tests
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,analysis]"
pytest
```

After installation, the `fare-signal` command is available.

## Run the development backtest

```bash
fare-signal backtest \
  --input data/sample_flight_trajectories.csv \
  --model models/price_model.joblib \
  --output artifacts/backtest_results.json
```

Outputs:

```text
artifacts/backtest_results.json
artifacts/backtest_decisions.csv
```

## Run the complete 82M-row workflow

The raw dataset is not committed. Place it anywhere locally and pass its path explicitly:

```bash
fare-signal ingest \
  --input "/Users/yuvia/Downloads/itineraries 2.csv" \
  --output data/flight_prices_clean.parquet

fare-signal build-table \
  --input data/flight_prices_clean.parquet \
  --output data/training_table.parquet

fare-signal train

fare-signal backtest \
  --input data/flight_prices_clean.parquet \
  --model models/price_model.joblib \
  --output artifacts/backtest_results.json
```

The cleaning stage writes a JSON data-quality profile beside its Parquet result. Training saves both
the versioned model bundle and `artifacts/model_evaluation.json`.

## API

Start FastAPI locally:

```bash
uvicorn api.predict:app --reload
```

Endpoints:

```text
GET  /health
POST /api/predict
GET  /api/backtest/results
GET  /docs
```

Example request:

```json
{
  "origin": "LAX",
  "destination": "BOS",
  "flightDate": "2026-10-15",
  "currentPrice": 275.0,
  "stops": "all"
}
```

The existing static site under `public/` sends the same request to `/api/predict`.

## Data scope

The model supports 16 airports and 235 learned directed routes from the source dataset. Full raw and
processed datasets are excluded from Git. Two development files are included:

- `sample_flight_prices_clean.csv`: small independent-row preview
- `sample_flight_trajectories.csv`: complete selected histories used for integration backtesting

Dataset source: [Flight Prices on Kaggle](https://www.kaggle.com/datasets/dilwong/flightprices).

## Limitations

- Historical quotes are observed offers, not completed purchases.
- The route-level target represents the cheapest observed market fare, not one immutable flight leg.
- Published-fare lookup is best-effort and should be replaced with a contracted provider for a
  production travel application.
- The verified development backtest shows that the current model is better at avoiding harmful waits
  than simple waiting baselines, but it does not yet beat always-buy on mean savings. The next model
  iteration should optimize the booking objective directly before claiming savings on a résumé.

## Résumé-safe description

> Built an end-to-end flight-fare decision platform over an 82M-row Expedia dataset, engineering an
> out-of-core DuckDB/Parquet pipeline, temporal gradient-boosting model, FastAPI inference service,
> and browser-based BUY/WAIT experience.

> Designed a leakage-aware booking simulator with validation-only policy selection and held-out
> comparisons against four baseline strategies; added versioned artifacts, 51 automated tests, and
> reproducible CLI workflows.
