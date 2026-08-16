import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

DATA_PATH = "data/training_table.parquet"
FEATURE_COLS = ["days_before_departure", "departure_day_of_week", "departure_month", "search_day_of_week"]

con = duckdb.connect()
df = con.execute(f"SELECT * FROM '{DATA_PATH}'").fetchdf()
df["route"] = df["startingAirport"] + "-" + df["destinationAirport"]
print(f"Loaded {len(df):,} rows, {df['route'].nunique()} routes")

# Time-based split: last 15% of flight dates become the test set, so we're
# evaluating "predict the future from the past", not a random shuffle that
# would leak nearby days between train and test.
unique_dates = np.sort(df["flightDate"].unique())
cutoff_date = unique_dates[int(len(unique_dates) * 0.85)]
train_df = df[df["flightDate"] < cutoff_date].copy()
test_df = df[df["flightDate"] >= cutoff_date].copy()
print(f"Train: {len(train_df):,} rows (flights before {cutoff_date})")
print(f"Test:  {len(test_df):,} rows (flights from {cutoff_date} on)")


def evaluate(name, y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    print(f"{name:22s} MAE=${mae:6.2f}   RMSE=${rmse:6.2f}")


print("\n=== Baseline: historical average fare per (route, days_before_departure) ===")
baseline_lookup = (
    train_df.groupby(["route", "days_before_departure"])["best_fare"]
    .mean()
    .reset_index()
    .rename(columns={"best_fare": "pred_baseline"})
)
global_mean = train_df["best_fare"].mean()
test_df = test_df.merge(baseline_lookup, on=["route", "days_before_departure"], how="left")
test_df["pred_baseline"] = test_df["pred_baseline"].fillna(global_mean)
evaluate("Historical average", test_df["best_fare"], test_df["pred_baseline"])

print("\n=== Random Forest (target-encoded route) ===")
# One-hot blew up to 235 sparse columns on ~1.7M rows (~3GB+ dense matrix) and
# thrashed this machine's memory. Target encoding (route -> its average fare,
# computed from train only to avoid leakage) keeps this to a single numeric
# column instead.
route_target = train_df.groupby("route")["best_fare"].mean()
train_df["route_encoded"] = train_df["route"].map(route_target)
test_df["route_encoded"] = test_df["route"].map(route_target).fillna(global_mean)

rf_features = ["route_encoded"] + FEATURE_COLS
rf = RandomForestRegressor(n_estimators=100, max_depth=14, n_jobs=2, random_state=42)
rf.fit(train_df[rf_features], train_df["best_fare"])
pred_rf = rf.predict(test_df[rf_features])
evaluate("Random Forest", test_df["best_fare"], pred_rf)

print("\n=== HistGradientBoosting (native categorical route) ===")
all_routes = df["route"].astype("category").cat.categories
X_train_hgb = train_df[["route"] + FEATURE_COLS].copy()
X_test_hgb = test_df[["route"] + FEATURE_COLS].copy()
X_train_hgb["route"] = X_train_hgb["route"].astype("category").cat.set_categories(all_routes)
X_test_hgb["route"] = X_test_hgb["route"].astype("category").cat.set_categories(all_routes)

hgb = HistGradientBoostingRegressor(categorical_features="from_dtype", max_iter=300, random_state=42)
hgb.fit(X_train_hgb, train_df["best_fare"])
pred_hgb = hgb.predict(X_test_hgb)
evaluate("HistGradientBoosting", test_df["best_fare"], pred_hgb)
