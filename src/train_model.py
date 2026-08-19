import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

DATA_PATH = "data/training_table.parquet"
FEATURE_COLS = [
    "days_before_departure", "departure_day_of_week", "departure_month", "search_day_of_week",
    "isNonStop", "isBasicEconomy", "totalTravelDistance",
]

con = duckdb.connect()
df = con.execute(f"SELECT * FROM '{DATA_PATH}'").fetchdf()
df["route"] = df["startingAirport"] + "-" + df["destinationAirport"]
print(f"Loaded {len(df):,} rows, {df['route'].nunique()} routes")

# Three-way time-based split: train (70%) to fit models, validation (15%) to
# compare hyperparameters, test (15%) touched exactly once at the end for the
# final reported number. Using the test set to pick hyperparameters would
# leak information and make the reported accuracy overly optimistic.
unique_dates = np.sort(df["flightDate"].unique())
train_cutoff = unique_dates[int(len(unique_dates) * 0.70)]
val_cutoff = unique_dates[int(len(unique_dates) * 0.85)]

train_df = df[df["flightDate"] < train_cutoff].copy()
val_df = df[(df["flightDate"] >= train_cutoff) & (df["flightDate"] < val_cutoff)].copy()
test_df = df[df["flightDate"] >= val_cutoff].copy()
print(f"Train: {len(train_df):,} rows (before {train_cutoff})")
print(f"Val:   {len(val_df):,} rows ({train_cutoff} to {val_cutoff})")
print(f"Test:  {len(test_df):,} rows (from {val_cutoff} on)\n")

global_mean = train_df["best_fare"].mean()
route_target = train_df.groupby("route")["best_fare"].mean()
for d in (train_df, val_df, test_df):
    d["route_encoded"] = d["route"].map(route_target).fillna(global_mean)

all_routes = df["route"].astype("category").cat.categories
for d in (train_df, val_df, test_df):
    d["route_cat"] = d["route"].astype("category").cat.set_categories(all_routes)


def mae_rmse(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    return mae, rmse


def report_fit(name, predict_fn):
    """Print train vs val MAE side by side - a big gap means overfitting."""
    train_mae, train_rmse = mae_rmse(train_df["best_fare"], predict_fn(train_df))
    val_mae, val_rmse = mae_rmse(val_df["best_fare"], predict_fn(val_df))
    gap = val_mae - train_mae
    flag = "  <-- overfitting (train much better than val)" if gap > train_mae * 0.5 else ""
    print(f"{name:32s} train MAE=${train_mae:6.2f}  val MAE=${val_mae:6.2f}  gap=${gap:6.2f}{flag}")
    return val_mae


print("=== Step 0: ablation - do isNonStop/isBasicEconomy/totalTravelDistance actually help? ===")
print("(same target, same train/val split - only the feature list differs)")
OLD_FEATURE_COLS = ["days_before_departure", "departure_day_of_week", "departure_month", "search_day_of_week"]
hgb_old_features = ["route_cat"] + OLD_FEATURE_COLS
hgb_ablation_old = HistGradientBoostingRegressor(categorical_features="from_dtype", max_iter=300, random_state=42)
hgb_ablation_old.fit(train_df[hgb_old_features], train_df["best_fare"])
report_fit("HGB, old features only", lambda d: hgb_ablation_old.predict(d[hgb_old_features]))

hgb_new_features = ["route_cat"] + FEATURE_COLS
hgb_ablation_new = HistGradientBoostingRegressor(categorical_features="from_dtype", max_iter=300, random_state=42)
hgb_ablation_new.fit(train_df[hgb_new_features], train_df["best_fare"])
report_fit("HGB, old + 3 new features", lambda d: hgb_ablation_new.predict(d[hgb_new_features]))

print("\n=== Step 1: overfitting check on the models we already have ===")

baseline_lookup = (
    train_df.groupby(["route", "days_before_departure"])["best_fare"]
    .mean()
    .rename("pred_baseline")
)


def predict_baseline(d):
    return d.set_index(["route", "days_before_departure"]).index.map(baseline_lookup).to_numpy(dtype=float)


# baseline can't predict for (route, day) combos it never saw in train - those
# come back as NaN, fill with the global mean like before
def predict_baseline_filled(d):
    pred = predict_baseline(d)
    return np.where(np.isnan(pred), global_mean, pred)


report_fit("Historical average", predict_baseline_filled)

rf_features = ["route_encoded"] + FEATURE_COLS
rf_default = RandomForestRegressor(n_estimators=100, max_depth=14, n_jobs=2, random_state=42)
rf_default.fit(train_df[rf_features], train_df["best_fare"])
report_fit("Random Forest (original config)", lambda d: rf_default.predict(d[rf_features]))

hgb_features = hgb_new_features  # reuse the model already fit in the step 0 ablation
hgb_default = hgb_ablation_new
report_fit("HistGradientBoosting (original config)", lambda d: hgb_default.predict(d[hgb_features]))

print("\n=== Step 2: try more regularized HistGradientBoosting configs on val ===")
hgb_configs = {
    "more trees, lower lr": dict(max_iter=600, learning_rate=0.05, max_leaf_nodes=31, random_state=42),
    "shallower + regularized": dict(max_iter=300, learning_rate=0.1, max_leaf_nodes=15,
                                     min_samples_leaf=50, l2_regularization=1.0, random_state=42),
    "deeper (more capacity)": dict(max_iter=300, learning_rate=0.1, max_leaf_nodes=63, random_state=42),
}

best_name, best_val_mae, best_model = None, float("inf"), hgb_default
val_mae_default = report_fit("  -> default (baseline for this step)", lambda d: hgb_default.predict(d[hgb_features]))
if val_mae_default < best_val_mae:
    best_name, best_val_mae = "default", val_mae_default

for name, params in hgb_configs.items():
    model = HistGradientBoostingRegressor(categorical_features="from_dtype", **params)
    model.fit(train_df[hgb_features], train_df["best_fare"])
    val_mae = report_fit(f"  -> {name}", lambda d, m=model: m.predict(d[hgb_features]))
    if val_mae < best_val_mae:
        best_name, best_val_mae, best_model = name, val_mae, model

print(f"\nBest config on validation: {best_name} (val MAE=${best_val_mae:.2f})")

print("\n=== Step 3: final, one-time evaluation on the untouched test set ===")
test_mae, test_rmse = mae_rmse(test_df["best_fare"], best_model.predict(test_df[hgb_features]))
print(f"Final HistGradientBoosting ({best_name}) on TEST: MAE=${test_mae:.2f}  RMSE=${test_rmse:.2f}")
