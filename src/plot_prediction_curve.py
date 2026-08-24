import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.remaining_curve import FEATURE_COLS, attach_features
import joblib

TABLE_PATH = "data/training_table.parquet"
MODEL_PATH = "models/price_model.joblib"
OUT_PATH = "notebooks/predicted_vs_actual_curve.png"
N_ROUTES = 4

bundle = joblib.load(MODEL_PATH)
model, route_categories = bundle["model"], bundle["route_categories"]
feature_cols = bundle.get("feature_cols", FEATURE_COLS)

con = duckdb.connect()
df = con.execute(f"SELECT * FROM '{TABLE_PATH}'").fetchdf()
df["route"] = df["startingAirport"] + "-" + df["destinationAirport"]
if "isNonStop" not in df.columns:
    df["isNonStop"] = False

top_routes = df["route"].value_counts().head(N_ROUTES).index.tolist()
print(f"Comparing predicted vs actual for: {top_routes}")

fig, axes = plt.subplots(2, 2, figsize=(14, 9))
axes = axes.flatten()

for ax, route in zip(axes, top_routes):
    route_df = df[df["route"] == route]
    flight_date = route_df["flightDate"].value_counts().idxmax()
    flight_rows = route_df[route_df["flightDate"] == flight_date].sort_values("days_before_departure")
    # default panel: cheapest of nonstop vs connecting when both exist
    if "isNonStop" in flight_rows.columns:
        any_rows = (
            flight_rows.groupby("days_before_departure", as_index=False)
            .agg(best_fare=("best_fare", "min"),
                 departure_day_of_week=("departure_day_of_week", "first"),
                 departure_month=("departure_month", "first"),
                 search_day_of_week=("search_day_of_week", "first"),
                 totalTravelDistance=("totalTravelDistance", "first"),
                 startingAirport=("startingAirport", "first"),
                 destinationAirport=("destinationAirport", "first"))
        )
        any_rows["isNonStop"] = False
        flight_rows = any_rows.sort_values("days_before_departure")

    ax.plot(flight_rows["days_before_departure"], flight_rows["best_fare"],
            marker="o", markersize=3, label="Actual", color="tab:blue")

    as_of_days = int(flight_rows["days_before_departure"].max())
    current_fare = float(flight_rows.loc[flight_rows["days_before_departure"] == as_of_days, "best_fare"].iloc[0])
    pred_input = flight_rows.copy()
    pred_input["as_of_days"] = as_of_days
    pred_input["current_fare"] = current_fare
    pred_input["flightDate"] = flight_date
    pred_input = attach_features(pred_input, route_categories)
    if bundle.get("model_kind") == "relative_remaining":
        rel = np.clip(model.predict(pred_input[feature_cols]), 0.3, 3.0)
        predicted = rel * current_fare
        predicted = np.where(pred_input["days_before_departure"].to_numpy() == as_of_days, current_fare, predicted)
    else:
        predicted = model.predict(pred_input[feature_cols])

    ax.plot(flight_rows["days_before_departure"], predicted,
            marker="x", markersize=4, label="Predicted (pinned to first observed fare)", color="tab:red")

    ax.set_title(f"{route}, flight date {flight_date}")
    ax.set_xlabel("Days before departure")
    ax.set_ylabel("Best fare ($)")
    ax.invert_xaxis()
    ax.legend()

fig.tight_layout()
fig.savefig(OUT_PATH, dpi=150)
print(f"Saved {OUT_PATH}")
