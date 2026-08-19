import duckdb
import os

IN_PATH = "data/flight_prices_clean.parquet"
OUT_PATH = "data/training_table.parquet"

con = duckdb.connect()

# Collapse the 82M cleaned rows down to one row per (route, flightDate,
# days_before_departure, isNonStop, isBasicEconomy), keeping the cheapest fare
# found in each group. isNonStop/isBasicEconomy stay as group keys (not
# aggregated away) so the model - and later the site - can tell "cheapest
# nonstop" apart from "cheapest overall". totalTravelDistance is folded in as
# a feature via its median, since it can still vary a little within a group
# (different connecting routings). This shrinks the row count from tens of
# millions to a manageable size for training.
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
            isBasicEconomy,
            MEDIAN(totalTravelDistance) AS totalTravelDistance,
            MIN(totalFare) AS best_fare
        FROM '{IN_PATH}'
        GROUP BY
            startingAirport, destinationAirport, flightDate, days_before_departure,
            departure_day_of_week, departure_month, search_day_of_week,
            isNonStop, isBasicEconomy
    ) TO '{OUT_PATH}' (FORMAT PARQUET)
""")

n = con.execute(f"SELECT COUNT(*) FROM '{OUT_PATH}'").fetchone()[0]
size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
print(f"Training table rows: {n:,}")
print(f"Training table size: {size_mb:.1f} MB")
