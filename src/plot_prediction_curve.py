import duckdb
import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TABLE_PATH = "data/training_table.parquet"
MODEL_PATH = "models/price_model.joblib"
OUT_PATH = "notebooks/predicted_vs_actual_curve.png"
N_ROUTES = 4

bundle = joblib.load(MODEL_PATH)
model, route_categories, feature_cols = bundle["model"], bundle["route_categories"], bundle["feature_cols"]

con = duckdb.connect()
df = con.execute(f"SELECT * FROM '{TABLE_PATH}'").fetchdf()
df["route"] = df["startingAirport"] + "-" + df["destinationAirport"]

top_routes = df["route"].value_counts().head(N_ROUTES).index.tolist()
print(f"Comparing predicted vs actual for: {top_routes}")

fig, axes = plt.subplots(2, 2, figsize=(14, 9))
axes = axes.flatten()

for ax, route in zip(axes, top_routes):
    route_df = df[df["route"] == route]

    # pick the flightDate with the most search-day observations, for a clean example
    flight_date = route_df["flightDate"].value_counts().idxmax()
    flight_rows = route_df[route_df["flightDate"] == flight_date].sort_values("days_before_departure")

    # actual: the real best_fare found on each day for this specific flight
    ax.plot(flight_rows["days_before_departure"], flight_rows["best_fare"],
            marker="o", markersize=3, label="Actual", color="tab:blue")

    # predicted: ask the model for every day_before_departure this flight actually
    # has data for, holding the flight's real departure_day_of_week/month/distance
    # fixed and only varying days_before_departure (and the search_day_of_week it implies)
    pred_input = flight_rows[["days_before_departure", "departure_day_of_week",
                               "departure_month", "totalTravelDistance"]].copy()
    # duckdb's dayofweek() is Sun=0..Sat=6, but pandas' dt.dayofweek is Mon=0..Sun=6 -
    # convert so this matches the convention the training table (and model) were built with
    search_dates = pd.to_datetime(flight_date) - pd.to_timedelta(pred_input["days_before_departure"], unit="D")
    pred_input["search_day_of_week"] = (search_dates.dt.dayofweek + 1) % 7
    pred_input["route_cat"] = pd.Categorical([route] * len(pred_input), categories=route_categories)

    predicted = model.predict(pred_input[feature_cols])
    ax.plot(flight_rows["days_before_departure"], predicted,
            marker="x", markersize=4, label="Predicted", color="tab:red")

    ax.set_title(f"{route}, flight date {flight_date}")
    ax.set_xlabel("Days before departure")
    ax.set_ylabel("Best fare ($)")
    ax.invert_xaxis()
    ax.legend()

fig.tight_layout()
fig.savefig(OUT_PATH, dpi=150)
print(f"Saved {OUT_PATH}")
