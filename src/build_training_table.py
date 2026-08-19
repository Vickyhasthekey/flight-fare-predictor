import duckdb
import os

IN_PATH = "data/flight_prices_clean.parquet"
OUT_PATH = "data/training_table.parquet"

con = duckdb.connect()

# Collapse the 82M cleaned rows down to one row per (route, flightDate,
# days_before_departure), keeping the overall cheapest fare found that day
# (any cabin, any stop count) - this is the "lowest price, period" target.
# isNonStop/isBasicEconomy are deliberately NOT group keys here - splitting by
# them makes the min() noisier (smaller pool per group) and is deferred to a
# later "nonstop only" feature/filter (see the isNonStop/isBasicEconomy
# version of this file, committed separately). totalTravelDistance is still
# folded in as a plain feature via its median, since that doesn't fragment
# the target.
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
            MEDIAN(totalTravelDistance) AS totalTravelDistance,
            MIN(totalFare) AS best_fare
        FROM '{IN_PATH}'
        GROUP BY
            startingAirport, destinationAirport, flightDate, days_before_departure,
            departure_day_of_week, departure_month, search_day_of_week
    ) TO '{OUT_PATH}' (FORMAT PARQUET)
""")

n = con.execute(f"SELECT COUNT(*) FROM '{OUT_PATH}'").fetchone()[0]
size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
print(f"Training table rows: {n:,}")
print(f"Training table size: {size_mb:.1f} MB")
