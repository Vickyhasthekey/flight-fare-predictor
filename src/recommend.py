import joblib
import numpy as np
import pandas as pd
from datetime import date, timedelta

from src.features import is_weekend_dow, near_holiday
from src.remaining_curve import FEATURE_COLS

MODEL_PATH = "models/price_model.joblib"
MAX_DAYS = 60
MIN_MEANINGFUL_SAVINGS = 8.0

_bundle = None


def set_bundle(bundle):
    """Tests inject a fake artifact so we don't load models/price_model.joblib."""
    global _bundle
    _bundle = bundle


def _get_bundle():
    global _bundle
    if _bundle is None:
        _bundle = joblib.load(MODEL_PATH)
    return _bundle


def _dow(d):
    # duckdb's dayofweek() is Sun=0..Sat=6; python's date.weekday() is Mon=0..Sun=6
    return (d.weekday() + 1) % 7


def _frame_for_curve(origin, destination, flight_date, current_price, today, is_nonstop, bundle):
    route = f"{origin}-{destination}"
    days_left = (flight_date - today).days
    days = list(range(MAX_DAYS, 0, -1))
    search_dates = [flight_date - timedelta(days=d) for d in days]
    distance = bundle["route_distance"].get(route, bundle["global_median_distance"])
    curve = pd.DataFrame({
        "days_before_departure": days,
        "as_of_days": days_left,
        "current_fare": current_price,
        "departure_day_of_week": _dow(flight_date),
        "departure_month": flight_date.month,
        "search_day_of_week": [_dow(d) for d in search_dates],
        "totalTravelDistance": distance,
        "is_nonstop": is_nonstop,
        "flightDate": flight_date,
        "route": route,
    })
    curve["log_current_fare"] = np.log(max(float(current_price), 1.0))
    curve["departure_is_weekend"] = is_weekend_dow(_dow(flight_date))
    curve["near_holiday"] = near_holiday(flight_date)
    curve["route_cat"] = pd.Categorical([route] * len(curve), categories=bundle["route_categories"])
    return curve


def _predict_relative(origin, destination, flight_date, current_price, today, is_nonstop, bundle):
    curve = _frame_for_curve(origin, destination, flight_date, current_price, today, is_nonstop, bundle)
    cols = bundle.get("feature_cols", FEATURE_COLS)
    rel = bundle["model"].predict(curve[cols])
    days_left = (flight_date - today).days
    fare = np.clip(rel, 0.3, 3.0) * float(current_price)
    curve["predicted_fare"] = fare
    curve.loc[curve["days_before_departure"] == days_left, "predicted_fare"] = float(current_price)
    return curve


def _resolved_current_price(origin, destination, current_price, bundle):
    if current_price is not None:
        return float(current_price)
    route = f"{origin}-{destination}"
    medians = bundle.get("route_median_fare")
    if medians is not None:
        return float(medians.get(route, bundle.get("global_median_fare", 150.0)))
    return float(bundle.get("global_median_fare", 150.0))


def predict_curve(origin, destination, flight_date, current_price=None, today=None, nonstop_only=False):
    """Remaining best-fare curve, pinned to today's observed price when given.

    nonstop_only=True uses the nonstop pool only. Otherwise the cheaper of
    nonstop vs connecting is used for each day, so connecting flights still
    participate in the prediction.
    """
    today = today or date.today()
    bundle = _get_bundle()
    price = _resolved_current_price(origin, destination, current_price, bundle)

    if bundle.get("model_kind") != "relative_remaining":
        return _predict_absolute_legacy(origin, destination, flight_date, bundle)

    connecting = _predict_relative(origin, destination, flight_date, price, today, False, bundle)
    if nonstop_only:
        return _predict_relative(origin, destination, flight_date, price, today, True, bundle)

    nonstop = _predict_relative(origin, destination, flight_date, price, today, True, bundle)
    mixed = connecting.copy()
    mixed["predicted_fare"] = np.minimum(connecting["predicted_fare"], nonstop["predicted_fare"])
    days_left = (flight_date - today).days
    mixed.loc[mixed["days_before_departure"] == days_left, "predicted_fare"] = float(price)
    return mixed


def _predict_absolute_legacy(origin, destination, flight_date, bundle):
    route = f"{origin}-{destination}"
    days = list(range(MAX_DAYS, 0, -1))
    search_dates = [flight_date - timedelta(days=d) for d in days]
    curve = pd.DataFrame({
        "days_before_departure": days,
        "departure_day_of_week": _dow(flight_date),
        "departure_month": flight_date.month,
        "search_day_of_week": [_dow(d) for d in search_dates],
        "totalTravelDistance": bundle["route_distance"].get(route, bundle["global_median_distance"]),
    })
    curve["route_cat"] = pd.Categorical([route] * len(curve), categories=bundle["route_categories"])
    curve["predicted_fare"] = bundle["model"].predict(curve[bundle["feature_cols"]])
    return curve


def _buy_window(remaining, best_day, best_price, margin=MIN_MEANINGFUL_SAVINGS):
    """Contiguous block of days around best_day within `margin` of the best price."""
    ordered = remaining.sort_values("days_before_departure", ascending=False).reset_index(drop=True)
    within = ordered["predicted_fare"] <= best_price + margin
    best_idx = ordered.index[ordered["days_before_departure"] == best_day][0]

    lo = hi = best_idx
    while lo > 0 and within[lo - 1]:
        lo -= 1
    while hi < len(ordered) - 1 and within[hi + 1]:
        hi += 1

    window_days = ordered.loc[lo:hi, "days_before_departure"]
    return int(window_days.max()), int(window_days.min())


def recommend_purchase_timing(origin, destination, flight_date, today=None,
                              current_price=None, nonstop_only=False):
    today = today or date.today()
    days_left = (flight_date - today).days

    if days_left <= 0:
        return {"status": "error", "message": "Flight date must be in the future."}
    if days_left > MAX_DAYS:
        return {
            "status": "too_far",
            "message": f"Flight is {days_left} days out - the model only has reliable data up to "
                       f"{MAX_DAYS} days before departure. Check back closer to the flight.",
        }

    curve = predict_curve(
        origin, destination, flight_date,
        current_price=current_price, today=today, nonstop_only=nonstop_only,
    )
    curve_records = curve[["days_before_departure", "predicted_fare"]].round(2).to_dict("records")
    pinned_price = float(curve.loc[curve["days_before_departure"] == days_left, "predicted_fare"].iloc[0])

    remaining = curve[curve["days_before_departure"] <= days_left]
    best_row = remaining.loc[remaining["predicted_fare"].idxmin()]
    best_day, best_price = int(best_row["days_before_departure"]), float(best_row["predicted_fare"])

    window_far_days, window_near_days = _buy_window(remaining, best_day, best_price)
    window_start = flight_date - timedelta(days=window_far_days)
    window_end = flight_date - timedelta(days=window_near_days)
    best_date = flight_date - timedelta(days=best_day)
    window_fields = {
        "best_day": best_day,
        "best_date": best_date.isoformat(),
        "buy_window_start": window_start.isoformat(),
        "buy_window_end": window_end.isoformat(),
        "buy_window_start_days": window_far_days,
        "buy_window_end_days": window_near_days,
    }

    savings = pinned_price - best_price
    if best_day == days_left or savings < MIN_MEANINGFUL_SAVINGS:
        return {
            "status": "buy_now",
            "current_price": round(pinned_price, 2),
            "days_left": days_left,
            "today": today.isoformat(),
            "curve": curve_records,
            "nonstop_only": bool(nonstop_only),
            "message": "Buy now - waiting isn't expected to save you money before departure.",
            **window_fields,
        }

    wait_days = days_left - best_day
    when_text = (
        f"around {best_date:%b %-d}" if window_start == window_end
        else f"between {window_start:%b %-d} and {window_end:%b %-d}"
    )
    return {
        "status": "wait",
        "wait_days": wait_days,
        "current_price": round(pinned_price, 2),
        "expected_best_price": round(best_price, 2),
        "expected_savings": round(savings, 2),
        "days_left": days_left,
        "today": today.isoformat(),
        "curve": curve_records,
        "nonstop_only": bool(nonstop_only),
        "message": f"Wait about {wait_days} more day(s) - buy {when_text}. "
                   f"You could save around ${savings:.2f} by waiting.",
        **window_fields,
    }


if __name__ == "__main__":
    examples = [
        ("ATL", "LAX", date.today() + timedelta(days=45), 180),
        ("ATL", "LAX", date.today() + timedelta(days=8), 220),
        ("LAX", "BOS", date.today() + timedelta(days=25), 250),
    ]
    for origin, destination, flight_date, price in examples:
        result = recommend_purchase_timing(
            origin, destination, flight_date, current_price=price,
        )
        print(f"{origin}->{destination}, flight {flight_date} @ ${price}:")
        print(f"  {result['message']}\n")
