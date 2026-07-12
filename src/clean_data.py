import duckdb
import time

IN_PATH = "data/flight_prices_slim.csv"
OUT_PATH = "data/flight_prices_clean.parquet"

con = duckdb.connect()

# Check row counts for each cleaning rule before touching the data,
# so we can see how much each rule would affect before applying it
print("=== Stats before cleaning ===")
stats = con.execute(f"""
    SELECT
        COUNT(*) AS total_rows,
        COUNT(*) FILTER (WHERE totalFare IS NULL OR totalFare <= 20 OR totalFare >= 5000) AS bad_fare_rows,
        COUNT(*) FILTER (WHERE flightDate < searchDate) AS bad_date_rows,
        COUNT(*) FILTER (WHERE seatsRemaining < 0) AS bad_seats_rows,
        COUNT(*) FILTER (WHERE totalTravelDistance IS NULL) AS missing_distance_rows
    FROM read_csv_auto('{IN_PATH}')
""").fetchone()

total, bad_fare, bad_date, bad_seats, missing_distance = stats
print(f"Total rows: {total:,}")
print(f"Bad fares (<=$20 or >=$5000 or null): {bad_fare:,} rows")
print(f"Bad dates (flightDate < searchDate): {bad_date:,} rows")
print(f"Negative seatsRemaining: {bad_seats:,} rows")
print(f"Missing totalTravelDistance: {missing_distance:,} rows (not dropped, imputed below)")

print("\n=== Cleaning + feature engineering ===")
start = time.time()

con.execute(f"""
    COPY (
        SELECT
            searchDate,
            flightDate,
            startingAirport,
            destinationAirport,
            totalFare,
            isNonStop,
            seatsRemaining,
            COALESCE(
                totalTravelDistance,
                MEDIAN(totalTravelDistance) OVER (PARTITION BY startingAirport, destinationAirport)
            ) AS totalTravelDistance,
            isBasicEconomy,
            date_diff('day', searchDate, flightDate) AS days_before_departure,
            dayofweek(flightDate) AS departure_day_of_week,
            month(flightDate) AS departure_month,
            dayofweek(searchDate) AS search_day_of_week
        FROM read_csv_auto('{IN_PATH}')
        WHERE totalFare > 20 AND totalFare < 5000
          AND flightDate >= searchDate
          AND (seatsRemaining IS NULL OR seatsRemaining >= 0)
    ) TO '{OUT_PATH}' (FORMAT PARQUET)
""")

elapsed = time.time() - start
print(f"Cleaning done in {elapsed:.1f}s")

# Stats after cleaning
after = con.execute(f"SELECT COUNT(*) FROM '{OUT_PATH}'").fetchone()[0]
print(f"\nRows after cleaning: {after:,} (from {total:,}, dropped {total - after:,} rows, {(total-after)/total*100:.2f}%)")

import os
size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
print(f"Output file size: {size_mb:.1f} MB (original csv was {os.path.getsize(IN_PATH) / (1024**3):.1f} GB)")
