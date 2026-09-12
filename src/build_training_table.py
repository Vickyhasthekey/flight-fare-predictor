import duckdb
import os

IN_PATH = "data/flight_prices_clean.parquet"
OUT_PATH = "data/training_table.parquet"

con = duckdb.connect()

# One row per (route, flightDate, days_before, isNonStop): cheapest fare in that
# stop-type pool. Connecting (isNonStop=false) and nonstop both stay in the
# table so either can be predicted; they are not mixed into one MIN().
con.execute(f"""
    COPY (
        SELECT
            startingAirport,
            destinationAirport,
            flightDate,
            days_before_departure,
            departure_day_of_week,
            departure_month,
            search_day_of_week,
            isNonStop,
            MEDIAN(totalTravelDistance) AS totalTravelDistance,
            MIN(totalFare) AS best_fare
        FROM '{IN_PATH}'
        GROUP BY
            startingAirport, destinationAirport, flightDate, days_before_departure,
            departure_day_of_week, departure_month, search_day_of_week, isNonStop
    ) TO '{OUT_PATH}' (FORMAT PARQUET)
""")

n = con.execute(f"SELECT COUNT(*) FROM '{OUT_PATH}'").fetchone()[0]
n_ns = con.execute(f"SELECT COUNT(*) FROM '{OUT_PATH}' WHERE isNonStop").fetchone()[0]
size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
print(f"Training table rows: {n:,} (nonstop {n_ns:,}, connecting {n - n_ns:,})")
print(f"Training table size: {size_mb:.1f} MB")
