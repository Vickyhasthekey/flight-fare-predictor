# Flight Price Prediction

Predict flight ticket prices from historical search data and tell travelers when
to buy — not just what a fare might be, but whether to buy now or wait, and what's the optimal purchase timing.

## Goal

Given a route and a flight date, predict how the price will move over the days
leading up to departure and recommend the best time to buy.

## Dataset

Source: [Flight Prices](https://www.kaggle.com/datasets/dilwong/flightprices) on
Kaggle (Expedia search data, ~82M rows, 31GB full file).

The raw and cleaned data files are not tracked in this repo (too large for git,
see `.gitignore`). To reproduce:

1. Download `itineraries.csv` from the Kaggle dataset above (or run the
   column-selection step in a Kaggle Notebook to avoid downloading the full
   31GB file locally).
2. Keep only these 9 columns, which is what `src/clean_data.py` expects:
   `searchDate`, `flightDate`, `startingAirport`, `destinationAirport`,
   `totalFare`, `isNonStop`, `seatsRemaining`, `totalTravelDistance`,
   `isBasicEconomy`.
3. Place the result at `data/flight_prices_slim.csv`.

## Project structure

```
data/         raw and cleaned data (gitignored, not tracked)
notebooks/    exploratory analysis
src/          data pipeline and modeling scripts
```

## Pipeline

1. **Clean + engineer features** (`src/clean_data.py`) — reads the slim CSV
   with DuckDB, drops rows with invalid fares or inconsistent dates, imputes
   missing travel distance from the route's median, and adds `days_before_departure`,
   `departure_day_of_week`, `departure_month`, and `search_day_of_week`. Writes
   `data/flight_prices_clean.parquet`.
2. **EDA** *(in progress)* — validate that price actually varies with
   `days_before_departure` in a predictable way, per route.
3. **Modeling** *(planned)* — predict `totalFare` from route + date features;
   for a given route/date, produce a full predicted price curve across future
   `days_before_departure` values.
4. **Recommendation engine** *(planned)* — compare a user's current position on
   the predicted price curve to its minimum, and recommend buy-now vs. wait
   (with an expected savings estimate).
5. **Web app** *(planned)* — user enters origin, destination, and flight date;
   the app returns the recommendation and a price chart.

## Setup

```bash
uv venv .venv
source .venv/bin/activate
uv pip install duckdb pandas
```

## Running the cleaning step

```bash
python src/clean_data.py
```
