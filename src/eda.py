import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_PATH = "data/flight_prices_clean.parquet"
OUT_DIR = "notebooks"
TOP_N_ROUTES = 5

con = duckdb.connect()

# 1. Find the busiest routes (most rows = most price history to learn from)
top_routes = con.execute(f"""
    SELECT startingAirport, destinationAirport, COUNT(*) AS n
    FROM '{DATA_PATH}'
    GROUP BY startingAirport, destinationAirport
    ORDER BY n DESC
    LIMIT {TOP_N_ROUTES}
""").fetchdf()
print("Top routes by row count:")
print(top_routes.to_string(index=False))

# 2. Average price curve per route: does price trend down with more lead time?
fig, ax = plt.subplots(figsize=(10, 6))
for _, row in top_routes.iterrows():
    origin, dest = row["startingAirport"], row["destinationAirport"]
    curve = con.execute("""
        SELECT days_before_departure, AVG(totalFare) AS avg_fare
        FROM read_parquet(?)
        WHERE startingAirport = ? AND destinationAirport = ?
          AND days_before_departure BETWEEN 0 AND 60
        GROUP BY days_before_departure
        ORDER BY days_before_departure
    """, [DATA_PATH, origin, dest]).fetchdf()
    ax.plot(curve["days_before_departure"], curve["avg_fare"], label=f"{origin}->{dest}")

ax.set_xlabel("Days before departure")
ax.set_ylabel("Average total fare ($)")
ax.set_title(f"Average price vs. days before departure (top {TOP_N_ROUTES} routes)")
ax.invert_xaxis()  # departure day (0) on the right, matches how people picture a timeline
ax.legend()
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/price_vs_days_before_departure.png", dpi=150)
print(f"\nSaved {OUT_DIR}/price_vs_days_before_departure.png")

# 3. One real flight's actual price trajectory, not an average - shows real noise
origin, dest = top_routes.iloc[0]["startingAirport"], top_routes.iloc[0]["destinationAirport"]
sample_flight = con.execute("""
    SELECT flightDate, COUNT(*) AS n
    FROM read_parquet(?)
    WHERE startingAirport = ? AND destinationAirport = ?
    GROUP BY flightDate
    ORDER BY n DESC
    LIMIT 1
""", [DATA_PATH, origin, dest]).fetchdf()
flight_date = sample_flight.iloc[0]["flightDate"]


# Without legId, one route+flightDate covers multiple distinct flights/fare
# classes per day, so we take the best (minimum) fare found each search day -
# this is also the number that actually matters for a "when's it cheapest" tool
trajectory = con.execute("""
    SELECT days_before_departure, MIN(totalFare) AS min_fare
    FROM read_parquet(?)
    WHERE startingAirport = ? AND destinationAirport = ? AND flightDate = ?
    GROUP BY days_before_departure
    ORDER BY days_before_departure DESC
""", [DATA_PATH, origin, dest, flight_date]).fetchdf()

fig2, ax2 = plt.subplots(figsize=(10, 6))
ax2.plot(trajectory["days_before_departure"], trajectory["min_fare"], marker="o", markersize=3)
ax2.set_xlabel("Days before departure")
ax2.set_ylabel("Best available fare ($)")
ax2.set_title(f"Real price trajectory (cheapest fare found per day): {origin}->{dest}, flight date {flight_date}")
ax2.invert_xaxis()
fig2.tight_layout()
fig2.savefig(f"{OUT_DIR}/single_flight_trajectory.png", dpi=150)
print(f"Saved {OUT_DIR}/single_flight_trajectory.png")

# 4. Correlation: how strong is the days_before_departure <-> price relationship?
print(f"\nCorrelation between days_before_departure and totalFare (top {TOP_N_ROUTES} routes):")
for _, row in top_routes.iterrows():
    origin, dest = row["startingAirport"], row["destinationAirport"]
    corr = con.execute("""
        SELECT CORR(days_before_departure, totalFare) AS corr
        FROM read_parquet(?)
        WHERE startingAirport = ? AND destinationAirport = ?
    """, [DATA_PATH, origin, dest]).fetchone()[0]
    print(f"{origin}->{dest}: corr = {corr:.4f}")
