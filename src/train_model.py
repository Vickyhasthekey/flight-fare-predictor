import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from src.metrics import buy_wait_agree, cheapest_day_error, curve_spearman
from src.remaining_curve import FEATURE_COLS, attach_features

DAILY_PATH = "data/training_table.parquet"
PAIRS_PATH = "data/remaining_pairs.parquet"
MODEL_PATH = "models/price_model.joblib"
AS_OF_STRIDE = 2
TIMING_SAMPLE = 1200
MIN_CURVE_DAYS = 8


def build_pairs():
    con = duckdb.connect()
    con.execute(f"""
        COPY (
            WITH daily AS (
                SELECT
                    startingAirport || '-' || destinationAirport AS route,
                    startingAirport,
                    destinationAirport,
                    flightDate,
                    isNonStop,
                    days_before_departure,
                    best_fare,
                    departure_day_of_week,
                    departure_month,
                    search_day_of_week,
                    totalTravelDistance,
                    CAST(flightDate AS DATE) - CAST(days_before_departure AS INTEGER) AS as_of_date
                FROM '{DAILY_PATH}'
            ),
            as_of AS (
                SELECT d.* FROM daily d
                INNER JOIN (
                    SELECT startingAirport, destinationAirport, flightDate, isNonStop,
                           MAX(days_before_departure) AS max_days
                    FROM daily
                    GROUP BY startingAirport, destinationAirport, flightDate, isNonStop
                ) m USING (startingAirport, destinationAirport, flightDate, isNonStop)
                WHERE d.days_before_departure = m.max_days
                   OR d.days_before_departure IN (21, 14, 7)
            )
            SELECT
                a.route,
                a.startingAirport,
                a.destinationAirport,
                a.flightDate,
                a.isNonStop,
                a.as_of_date,
                a.days_before_departure AS as_of_days,
                b.days_before_departure,
                a.best_fare AS current_fare,
                b.best_fare AS future_fare,
                LEAST(3.0, GREATEST(0.3, b.best_fare / a.best_fare)) AS rel_fare,
                a.departure_day_of_week,
                a.departure_month,
                b.search_day_of_week,
                a.totalTravelDistance
            FROM as_of a
            INNER JOIN daily b
              ON a.startingAirport = b.startingAirport
             AND a.destinationAirport = b.destinationAirport
             AND a.flightDate = b.flightDate
             AND a.isNonStop = b.isNonStop
            WHERE b.days_before_departure <= a.days_before_departure
              AND a.best_fare > 1
        ) TO '{PAIRS_PATH}' (FORMAT PARQUET)
    """)
    n = con.execute(f"SELECT COUNT(*) FROM '{PAIRS_PATH}'").fetchone()[0]
    print(f"Remaining-curve pairs: {n:,}")
    return n


def time_split(df, date_col):
    unique_dates = np.sort(df[date_col].unique())
    train_cutoff = unique_dates[int(len(unique_dates) * 0.70)]
    val_cutoff = unique_dates[int(len(unique_dates) * 0.85)]
    train = df[df[date_col] < train_cutoff].copy()
    val = df[(df[date_col] >= train_cutoff) & (df[date_col] < val_cutoff)].copy()
    test = df[df[date_col] >= val_cutoff].copy()
    print(f"Train: {len(train):,}  Val: {len(val):,}  Test: {len(test):,}")
    print(f"  cutoffs as_of_date < {train_cutoff} / < {val_cutoff}")
    return train, val, test, train_cutoff, val_cutoff


def dollar_metrics(y, p):
    mae = mean_absolute_error(y, p)
    rmse = float(np.sqrt(mean_squared_error(y, p)))
    return mae, rmse


def score_timing(daily, model, route_categories, n_curves=TIMING_SAMPLE, seed=0):
    """Buy/wait + cheapest-day + Spearman on sampled (route, date, stop-type) curves."""
    daily = daily.copy()
    if "route" not in daily.columns:
        daily["route"] = daily["startingAirport"] + "-" + daily["destinationAirport"]
    keys = ["route", "flightDate", "isNonStop"]
    eligible = daily.groupby(keys).size().reset_index(name="n")
    eligible = eligible[eligible["n"] >= MIN_CURVE_DAYS]
    if len(eligible) == 0:
        return {"buy_wait": 0.0, "median_best_day_err": 99.0, "median_spearman": 0.0, "remain_rmse": 999.0, "n": 0}
    sample = eligible.sample(n=min(n_curves, len(eligible)), random_state=seed)
    subset = daily.merge(sample[keys], on=keys)

    buy, err, spear, sq = [], [], [], []
    for _, g in subset.groupby(keys, sort=False):
        available = np.sort(g["days_before_departure"].unique())
        as_of_days = int(available[np.argmin(np.abs(available - 21))])
        if as_of_days < 5:
            continue
        as_of_fare = float(g.loc[g["days_before_departure"] == as_of_days, "best_fare"].iloc[0])
        rem = g[g["days_before_departure"] <= as_of_days].copy()
        rem["as_of_days"] = as_of_days
        rem["current_fare"] = as_of_fare
        feat = attach_features(rem, route_categories)
        pred = np.clip(model.predict(feat[FEATURE_COLS]), 0.3, 3.0) * as_of_fare
        pred = np.where(rem["days_before_departure"].to_numpy() == as_of_days, as_of_fare, pred)
        days = rem["days_before_departure"].to_numpy()
        actual = rem["best_fare"].to_numpy()
        buy.append(buy_wait_agree(days, actual, pred, as_of_days))
        err.append(cheapest_day_error(days, actual, pred))
        sp = curve_spearman(actual, pred)
        if np.isfinite(sp):
            spear.append(sp)
        sq.append(np.mean((actual - pred) ** 2))

    return {
        "buy_wait": float(np.mean(buy)) if buy else 0.0,
        "median_best_day_err": float(np.median(err)) if err else 99.0,
        "median_spearman": float(np.median(spear)) if spear else 0.0,
        "remain_rmse": float(np.sqrt(np.mean(sq))) if sq else 999.0,
        "n": len(buy),
    }


def report_timing(name, stats):
    print(
        f"{name:32s} buy/wait={stats['buy_wait']:.3f}  "
        f"best-day err={stats['median_best_day_err']:.1f}d  "
        f"Spearman={stats['median_spearman']:.3f}  "
        f"remain RMSE=${stats['remain_rmse']:.2f}  n={stats['n']}"
    )
    return (stats["buy_wait"], -stats["median_best_day_err"], stats["median_spearman"])


def main():
    if not os.path.exists(PAIRS_PATH):
        print("=== Building remaining-curve pairs (searchDate walk-forward) ===")
        build_pairs()
    else:
        print(f"Using existing {PAIRS_PATH}")

    con = duckdb.connect()
    n_pairs = con.execute(f"SELECT COUNT(*) FROM '{PAIRS_PATH}'").fetchone()[0]
    max_pairs = 3_000_000
    if n_pairs > max_pairs:
        print(f"Sampling {max_pairs:,} of {n_pairs:,} pairs for fitting (timing eval still uses full daily curves)")
        pairs = con.execute(
            f"SELECT * FROM '{PAIRS_PATH}' USING SAMPLE {max_pairs} (reservoir, 42)"
        ).fetchdf()
    else:
        pairs = con.execute(f"SELECT * FROM '{PAIRS_PATH}'").fetchdf()
    daily = con.execute(f"SELECT * FROM '{DAILY_PATH}'").fetchdf()
    pairs["as_of_date"] = pd.to_datetime(pairs["as_of_date"])
    daily["flightDate"] = pd.to_datetime(daily["flightDate"])
    pairs["route"] = pairs["startingAirport"] + "-" + pairs["destinationAirport"]
    print(f"Loaded {len(pairs):,} pairs, {len(daily):,} daily rows")

    train, val, test, train_cutoff, val_cutoff = time_split(pairs, "as_of_date")
    daily["route"] = daily["startingAirport"] + "-" + daily["destinationAirport"]
    all_routes = daily["route"].astype("category").cat.categories

    train_f = attach_features(train, all_routes)
    val_f = attach_features(val, all_routes)
    test_f = attach_features(test, all_routes)

    daily["searchDate"] = daily["flightDate"] - pd.to_timedelta(daily["days_before_departure"], unit="D")
    daily_val = daily[
        (daily["searchDate"] >= pd.Timestamp(train_cutoff))
        & (daily["searchDate"] < pd.Timestamp(val_cutoff))
    ]
    daily_test = daily[daily["searchDate"] >= pd.Timestamp(val_cutoff)]

    configs = {
        "default": dict(max_iter=300, learning_rate=0.1, max_leaf_nodes=31, random_state=42),
        "more trees, lower lr": dict(max_iter=500, learning_rate=0.05, max_leaf_nodes=31, random_state=42),
        "shallower + regularized": dict(
            max_iter=300, learning_rate=0.08, max_leaf_nodes=15,
            min_samples_leaf=50, l2_regularization=1.0, random_state=42,
        ),
    }

    print("\n=== Fit relative remaining-curve models; select on timing metrics ===")
    best_name, best_key, best_model = None, None, None
    for name, params in configs.items():
        model = HistGradientBoostingRegressor(categorical_features="from_dtype", **params)
        model.fit(train_f[FEATURE_COLS], train_f["rel_fare"])
        stats = score_timing(daily_val, model, all_routes)
        key = report_timing(name, stats)
        if best_key is None or key > best_key:
            best_name, best_key, best_model = name, key, model

    print(f"\nBest on validation: {best_name}")

    print("\n=== Test (searchDate holdout) ===")
    test_stats = score_timing(daily_test, best_model, all_routes, n_curves=min(2000, TIMING_SAMPLE * 2), seed=1)
    report_timing(f"TEST {best_name}", test_stats)
    pred_rel = np.clip(best_model.predict(test_f[FEATURE_COLS]), 0.3, 3.0)
    pred_fare = pred_rel * test_f["current_fare"].to_numpy()
    # pin same-day
    same = test_f["days_before_departure"].to_numpy() == test_f["as_of_days"].to_numpy()
    pred_fare = np.where(same, test_f["current_fare"].to_numpy(), pred_fare)
    mae, rmse = dollar_metrics(test_f["future_fare"], pred_fare)
    print(f"TEST remaining-curve MAE=${mae:.2f}  RMSE=${rmse:.2f}  (diagnostic, not the selection metric)")

    print("\n=== Refit on train+val and save ===")
    best_params = {p: v for p, v in best_model.get_params().items() if v is not None}
    final_model = HistGradientBoostingRegressor(**best_params)
    train_plus_val = pd.concat([train_f, val_f], ignore_index=True)
    final_model.fit(train_plus_val[FEATURE_COLS], train_plus_val["rel_fare"])

    route_distance = daily.groupby("route")["totalTravelDistance"].median()
    route_median_fare = daily.groupby("route")["best_fare"].median()

    os.makedirs("models", exist_ok=True)
    evaluation = {
        "model_selection": "validation BUY/WAIT agreement, cheapest-day error, and curve Spearman",
        "selected_configuration": best_name,
        "train_rows": len(train),
        "validation_rows": len(val),
        "test_rows": len(test),
        "train_cutoff": str(pd.Timestamp(train_cutoff).date()),
        "test_cutoff": str(pd.Timestamp(val_cutoff).date()),
        "test_buy_wait_agreement": test_stats["buy_wait"],
        "test_median_best_day_error": test_stats["median_best_day_err"],
        "test_median_curve_spearman": test_stats["median_spearman"],
        "test_remaining_curve_rmse": test_stats["remain_rmse"],
        "test_pair_mae_dollars": float(mae),
        "test_pair_rmse_dollars": float(rmse),
    }
    joblib.dump({
        "model": final_model,
        "model_kind": "relative_remaining",
        "model_version": "0.1.0",
        "route_categories": all_routes,
        "feature_cols": FEATURE_COLS,
        "route_distance": route_distance,
        "global_median_distance": float(daily["totalTravelDistance"].median()),
        "route_median_fare": route_median_fare,
        "global_median_fare": float(daily["best_fare"].median()),
        "evaluation": evaluation,
    }, MODEL_PATH)
    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/model_evaluation.json", "w", encoding="utf-8") as handle:
        json.dump(evaluation, handle, indent=2)
    print(f"Saved {MODEL_PATH}")
    print("Saved artifacts/model_evaluation.json")


if __name__ == "__main__":
    main()
