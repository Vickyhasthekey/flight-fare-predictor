import numpy as np
import pandas as pd

from src.features import is_weekend_dow, near_holiday

FEATURE_COLS = [
    "route_cat", "is_nonstop", "days_before_departure", "as_of_days",
    "log_current_fare", "departure_day_of_week", "departure_month",
    "search_day_of_week", "totalTravelDistance", "departure_is_weekend",
    "near_holiday",
]

PAIR_KEYS = ["startingAirport", "destinationAirport", "flightDate", "isNonStop"]


def make_remaining_pairs(daily, as_of_stride=2):
    """One row per (as-of day, future-or-same day) on the same route/date/stop type.

    Target is future_fare / current_fare. Same-day pairs have rel_fare=1 so the
    model can learn to pin today's observed price.
    """
    df = daily.copy()
    as_of = df
    if as_of_stride > 1:
        keep = (as_of["days_before_departure"] % as_of_stride == 0) | (as_of["days_before_departure"] <= 7)
        as_of = as_of.loc[keep]

    left = as_of[PAIR_KEYS + [
        "days_before_departure", "best_fare", "departure_day_of_week",
        "departure_month", "totalTravelDistance",
    ]].rename(columns={
        "days_before_departure": "as_of_days",
        "best_fare": "current_fare",
    })
    right = df[PAIR_KEYS + [
        "days_before_departure", "best_fare", "search_day_of_week",
    ]].rename(columns={"best_fare": "future_fare"})

    pairs = left.merge(right, on=PAIR_KEYS)
    pairs = pairs[pairs["days_before_departure"] <= pairs["as_of_days"]]
    pairs = pairs[pairs["current_fare"] > 1]
    pairs["rel_fare"] = (pairs["future_fare"] / pairs["current_fare"]).clip(0.3, 3.0)
    return pairs.reset_index(drop=True)


def attach_features(df, route_categories):
    out = df.copy()
    if "route" not in out.columns:
        out["route"] = out["startingAirport"] + "-" + out["destinationAirport"]
    if "is_nonstop" not in out.columns:
        out["is_nonstop"] = out["isNonStop"]
    out["is_nonstop"] = out["is_nonstop"].astype(bool)
    out["log_current_fare"] = np.log(np.clip(out["current_fare"].astype(float), 1.0, None))
    out["departure_is_weekend"] = out["departure_day_of_week"].map(is_weekend_dow)
    flight_dates = pd.to_datetime(out["flightDate"])
    unique_flags = {d.date(): near_holiday(d.date()) for d in flight_dates.drop_duplicates()}
    out["near_holiday"] = flight_dates.dt.date.map(unique_flags)
    out["route_cat"] = pd.Categorical(out["route"], categories=route_categories)
    return out
